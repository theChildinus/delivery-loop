#!/usr/bin/env python3
"""Safely migrate delivery-loop state versions 1-4 and upgrade pre-layout v5 state."""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path

import validate_delivery_state as validator


REVIEWED = {"review_failed", "review_passed", "done"}


def layout_metadata(goal: dict, tasks: list[dict]) -> dict:
    state_path = str(goal.get("state_path") or validator.LEGACY_FIXED_STATE_PATH)
    goal_root = validator.goal_root_from_state_path(state_path)
    origin = "legacy_fixed" if state_path == validator.LEGACY_FIXED_STATE_PATH else "goal_scoped"
    legacy_documents = []
    legacy_reviews = []
    if origin == "legacy_fixed":
        legacy_documents = [
            path for task in tasks
            if isinstance((path := task.get("document_path")), str) and path != path.lower()
        ]
        legacy_reviews = [
            path for task in tasks for path in valid_strings(task.get("review_artifacts"))
            if path != path.lower()
        ]
        for task in tasks:
            old_review = task.get("review_artifact")
            if isinstance(old_review, str) and old_review.strip() and old_review != old_review.lower():
                legacy_reviews.append(old_review.strip())
    return {
        "origin": origin,
        "delivery_root": validator.DEFAULT_DELIVERY_ROOT,
        "goal_root": goal_root,
        "legacy_document_paths": list(dict.fromkeys(legacy_documents)),
        "legacy_review_artifacts": list(dict.fromkeys(legacy_reviews)),
    }


def normalize_id(prefix: str, value: object, fallback: str) -> str:
    raw = str(value or fallback)
    for old_prefix in ("EPIC-", "GOAL-", "STORY-", "FEATURE-", "TASK-"):
        if raw.startswith(old_prefix):
            raw = raw.removeprefix(old_prefix)
            break
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-") or fallback
    return f"{prefix}-{suffix}"


def valid_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def migrate(source: dict) -> dict:
    if not isinstance(source, dict):
        raise ValueError("source state must be an object")
    version = source.get("schema_version")
    if version == 5:
        if isinstance(source.get("layout"), dict):
            raise ValueError("source v5 state already contains layout metadata")
        upgraded = copy.deepcopy(source)
        goal = upgraded.get("goal")
        tasks = upgraded.get("tasks")
        if not isinstance(goal, dict) or not isinstance(tasks, list) or not tasks:
            raise ValueError("source v5 state must contain goal and tasks")
        upgraded["layout"] = layout_metadata(goal, tasks)
        return upgraded
    if version not in {1, 2, 3, 4}:
        raise ValueError("source schema_version must be between 1 and 5")
    state = copy.deepcopy(source)
    goal = state.pop("goal", None) or state.pop("epic", None)
    tasks = state.get("tasks")
    if not isinstance(goal, dict):
        raise ValueError("source must contain goal or epic object")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("source tasks must be a non-empty array")
    original_goal_snapshot = copy.deepcopy(goal)

    raw_task_ids: list[str] = []
    task_id_map: dict[str, str] = {}
    used_task_ids: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError("every legacy Task must be an object")
        raw_id = str(task.get("id", index))
        if raw_id in task_id_map:
            raise ValueError(f"duplicate legacy Task id: {raw_id}")
        normalized = normalize_id("TASK", raw_id, f"{index:03d}")
        if normalized in used_task_ids:
            normalized = normalize_id("TASK", f"{normalized.removeprefix('TASK-')}-{index}", f"{index:03d}")
        raw_task_ids.append(raw_id)
        task_id_map[raw_id] = normalized
        used_task_ids.add(normalized)

    goal_id = normalize_id("GOAL", goal.get("id"), "001")
    original_goal_status = goal.get("status", "awaiting_plan_approval")
    if original_goal_status not in validator.GOAL_STATES:
        raise ValueError(f"invalid legacy Goal status: {original_goal_status!r}")
    goal["id"] = goal_id
    goal["history_origin"] = "legacy"
    goal["legacy_snapshot"] = original_goal_snapshot
    goal["title"] = str(goal.get("title") or "Legacy Goal - verify title")
    goal["plan_approved"] = bool(goal.get("plan_approved", original_goal_status != "awaiting_plan_approval"))
    goal["human_gate"] = bool(goal.get("human_gate", True))
    source_state_path = goal.get("state_path")
    source_plan_path = goal.get("plan_path")
    if source_state_path:
        goal["state_path"] = str(source_state_path)
    elif source_plan_path:
        goal["state_path"] = f"{Path(str(source_plan_path)).parent.as_posix()}/state.json"
    else:
        goal["state_path"] = validator.LEGACY_FIXED_STATE_PATH
    goal_root = validator.goal_root_from_state_path(goal["state_path"])
    goal["plan_path"] = str(source_plan_path or f"{goal_root}/plan.md")
    goal["document_mode"] = goal.get("document_mode") or ("small" if len(tasks) == 1 else "decomposed")
    goal["acceptance_evidence"] = valid_strings(goal.get("acceptance_evidence"))
    goal["acceptance_origin"] = None
    goal["acceptance_files"] = valid_strings(goal.get("acceptance_files"))
    goal["acceptance_commit_message"] = (
        goal.get("acceptance_commit_message")
        if isinstance(goal.get("acceptance_commit_message"), str) and goal["acceptance_commit_message"].strip()
        else None
    )
    goal_gaps: list[str] = []
    if original_goal_status == "accepted":
        if not goal["acceptance_evidence"]:
            goal_gaps.append("human_acceptance_evidence")
        if not goal["acceptance_commit_message"] or goal["state_path"] not in goal["acceptance_files"]:
            goal_gaps.append("acceptance_git_archive")
    goal["legacy_previous_status"] = None
    goal["legacy_gaps"] = goal_gaps
    goal["legacy_v5_digest"] = None
    goal["status"] = original_goal_status
    goal["status_history"] = [original_goal_status]
    goal["blocked_reason"] = goal.get("blocked_reason")

    feature_map: dict[str, str] = {}
    used_feature_ids: set[str] = set()
    earlier_ids: list[str] = []
    migrated_tasks: list[dict] = []
    for index, task in enumerate(tasks):
        original_task_snapshot = copy.deepcopy(task)
        original_task_snapshot.pop("commit", None)
        raw_id = raw_task_ids[index]
        task_id = task_id_map[raw_id]
        task["id"] = task_id
        raw_feature = task.pop("feature_id", task.pop("story_id", None))
        feature_id = None
        if raw_feature is not None:
            raw_feature_key = str(raw_feature)
            if raw_feature_key not in feature_map:
                normalized = normalize_id("FEATURE", raw_feature_key, f"{len(feature_map) + 1:03d}")
                if normalized in used_feature_ids:
                    normalized = normalize_id("FEATURE", f"{normalized.removeprefix('FEATURE-')}-{len(feature_map) + 1}", "001")
                feature_map[raw_feature_key] = normalized
                used_feature_ids.add(normalized)
            feature_id = feature_map[raw_feature_key]
        task["feature_id"] = feature_id

        original_status = task.get("status", "planned")
        if original_status not in validator.TASK_STATES:
            raise ValueError(f"{task_id}: invalid legacy status {original_status!r}")
        task["history_origin"] = "legacy"
        task["legacy_snapshot"] = original_task_snapshot
        task["title"] = str(task.get("title") or f"Legacy {task_id} - verify title")
        dependencies = task.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise ValueError(f"{task_id}: legacy dependencies must be an array")
        task["dependencies"] = [task_id_map.get(str(item), normalize_id("TASK", item, "unknown")) for item in dependencies]
        task["document_path"] = str(
            task.get("document_path")
            or (
                goal["plan_path"]
                if goal["document_mode"] == "small"
                else f"{goal_root}/tasks/{task_id.lower()}.md"
            )
        )
        task.setdefault("base_commit", None)
        task["review_round"] = task.get("review_round", 0) if isinstance(task.get("review_round", 0), int) else 0
        task["review_verdict"] = task.get("review_verdict")
        old_review_artifact = task.pop("review_artifact", None)
        task["review_artifacts"] = valid_strings(task.get("review_artifacts"))
        if not task["review_artifacts"] and isinstance(old_review_artifact, str) and old_review_artifact.strip():
            task["review_artifacts"] = [old_review_artifact.strip()]
        for field in ("review_evidence", "self_test_evidence", "regression_evidence", "validation_evidence"):
            task[field] = valid_strings(task.get(field))
        task["regression_task_ids"] = list(earlier_ids) if original_status in REVIEWED else []
        task["archive_files"] = valid_strings(task.get("archive_files"))
        old_commit = task.pop("commit", None)
        old_commit = old_commit if isinstance(old_commit, str) and re.fullmatch(r"[0-9a-fA-F]{7,64}", old_commit) else None
        task["legacy_archive_commit"] = old_commit
        task["archive_origin"] = None
        task["legacy_v5_digest"] = None
        task["archive_commit_message"] = f"legacy-commit:{old_commit}" if original_status == "done" and old_commit else None

        gaps: list[str] = []
        if original_status in REVIEWED:
            if task["review_round"] < 1:
                gaps.append("review_round")
            expected_verdict = "FAIL" if original_status == "review_failed" else "PASS"
            if task["review_verdict"] != expected_verdict:
                gaps.append("review_verdict")
            if not task["review_artifacts"]:
                gaps.append("review_artifacts")
            for field in ("review_evidence", "self_test_evidence", "regression_evidence", "validation_evidence"):
                if not task[field]:
                    gaps.append(field)
        if original_status == "done":
            if not old_commit:
                gaps.append("task_git_archive")
            required_files = {goal["state_path"], task["document_path"], *task["review_artifacts"]}
            if not required_files.issubset(set(task["archive_files"])):
                gaps.append("archive_files")

        task["legacy_previous_status"] = None
        task["legacy_gaps"] = gaps
        if gaps:
            task["legacy_previous_status"] = original_status
            task["status"] = "blocked"
            task["status_history"] = ["blocked"]
            task["blocked_reason"] = "legacy verification required: " + ", ".join(gaps)
            task["archive_commit_message"] = None
            task["archive_origin"] = None
        else:
            task["status"] = original_status
            task["status_history"] = [original_status]
            task["blocked_reason"] = (
                str(task.get("blocked_reason") or "legacy blocked reason unavailable")
                if original_status == "blocked" else None
            )
            if original_status == "done":
                task["archive_origin"] = "legacy"
                task["legacy_v5_digest"] = validator.stable_digest(task)
        migrated_tasks.append(task)
        earlier_ids.append(task_id)

    if original_goal_status in {"awaiting_acceptance", "accepted"} and any(
        task["status"] != "done" for task in migrated_tasks
    ):
        goal_gaps.append("task_verification_required")
    if goal_gaps:
        goal["legacy_previous_status"] = original_goal_status
        goal["status"] = "blocked"
        goal["status_history"] = ["blocked"]
        goal["blocked_reason"] = "legacy verification required: " + ", ".join(dict.fromkeys(goal_gaps))
        goal["acceptance_commit_message"] = None
        goal["acceptance_origin"] = None
        goal["acceptance_files"] = []
    elif goal["status"] == "blocked" and not goal.get("blocked_reason"):
        goal["blocked_reason"] = "legacy blocked reason unavailable"
    elif goal["status"] == "accepted":
        goal["acceptance_origin"] = "legacy"
        goal["legacy_v5_digest"] = validator.stable_digest(goal)

    state = {
        "schema_version": 5,
        "migration": {
            "source_schema": version,
            "legacy_goal": True,
            "legacy_task_ids": [task["id"] for task in migrated_tasks],
        },
        "layout": layout_metadata(goal, migrated_tasks),
        "goal": goal,
        "features": [
            {"id": feature_id, "title": f"Legacy {feature_id} - verify title"}
            for feature_id in feature_map.values()
        ],
        "tasks": migrated_tasks,
    }
    return state


def validate_candidate(state: dict) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(state, handle)
        handle.flush()
        validator.validate(Path(handle.name))


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: migrate_delivery_state.py <input-v1-v5.json> <output.json>", file=sys.stderr)
        return 2
    source_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    if source_path.resolve() == output_path.resolve():
        print("refusing to overwrite input; choose a different output path", file=sys.stderr)
        return 2
    if output_path.exists():
        print(f"refusing to overwrite existing output: {output_path}", file=sys.stderr)
        return 2
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        migrated = migrate(source)
        validate_candidate(migrated)
        output_path.write_text(json.dumps(migrated, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MIGRATION FAILED: {exc}", file=sys.stderr)
        return 1
    gap_count = len(migrated["goal"]["legacy_gaps"]) + sum(
        len(task["legacy_gaps"]) for task in migrated["tasks"]
    )
    print(f"MIGRATED: {source_path} -> {output_path}")
    if gap_count:
        print(f"Legacy verification gaps: {gap_count}. Blocked entities require explicit verification.")
    else:
        print("Legacy verification gaps: 0. Candidate state is structurally ready for inspection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
