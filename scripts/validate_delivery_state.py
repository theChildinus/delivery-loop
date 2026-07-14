#!/usr/bin/env python3
"""Validate delivery-loop state and optionally verify Task archives in Git."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


GOAL_STATES = {
    "awaiting_plan_approval", "in_progress", "awaiting_acceptance", "accepted", "blocked"
}
TASK_STATES = {
    "planned", "ready", "in_progress", "review_failed", "review_passed", "blocked", "done"
}
GOAL_TRANSITIONS = {
    "awaiting_plan_approval": {"in_progress", "blocked"},
    "in_progress": {"awaiting_acceptance", "blocked"},
    "awaiting_acceptance": {"accepted", "in_progress", "blocked"},
    "accepted": set(),
    "blocked": {"awaiting_plan_approval", "in_progress", "awaiting_acceptance"},
}
TASK_TRANSITIONS = {
    "planned": {"ready", "blocked"},
    "ready": {"in_progress", "blocked"},
    "in_progress": {"review_failed", "review_passed", "blocked"},
    "review_failed": {"in_progress", "blocked"},
    "review_passed": {"done", "in_progress", "blocked"},
    "blocked": {"planned", "ready", "in_progress"},
    "done": set(),
}
ACTIVE_TASK_STATES = {"ready", "in_progress", "review_failed", "review_passed"}
REVIEWED_TASK_STATES = {"review_failed", "review_passed", "done"}
PASSING_TASK_STATES = {"review_passed", "done"}
LEGACY_FIXED_STATE_PATH = "docs/delivery/state.json"
DEFAULT_DELIVERY_ROOT = "docs/delivery"
CODE_ONLY_ARCHIVE_MODE = "code_only"


def fail(message: str) -> None:
    raise ValueError(message)


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a non-empty string")
    return value


def canonical_relative_path(value: object, label: str) -> str:
    path = require_string(value, label)
    parsed = PurePosixPath(path)
    if "\\" in path or parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != path:
        fail(f"{label} must be a normalized repository-relative POSIX path")
    return path


def goal_root_from_state_path(state_path: str) -> str:
    parsed = PurePosixPath(state_path)
    if parsed.name != "state.json" or str(parsed.parent) == ".":
        fail("goal.state_path must end with <goal-root>/state.json")
    return parsed.parent.as_posix()


def require_under_goal_root(path: str, goal_root: str, label: str) -> None:
    if not path.startswith(goal_root + "/"):
        fail(f"{label} must be inside Goal root {goal_root!r}")


def path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def validate_delivery_file_ownership(
    path: str, delivery_root: str, goal_root: str, layout_origin: str, label: str
) -> None:
    if not path_is_within(path, delivery_root):
        return
    if layout_origin == "goal_scoped" and not path_is_within(path, goal_root):
        fail(f"{label} cannot include another Goal's delivery artifacts")
    if layout_origin == "legacy_fixed":
        relative = PurePosixPath(path).relative_to(PurePosixPath(delivery_root))
        if relative.parts and relative.parts[0].startswith("goal-"):
            fail(f"{label} cannot include a Goal-scoped delivery directory")


def validate_string_list(value: object, label: str, required: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        fail(f"{label} must be an array of non-empty strings")
    if required and not value:
        fail(f"{label} must not be empty")
    return value


def stable_digest(entity: dict, digest_field: str = "legacy_v5_digest") -> str:
    payload = dict(entity)
    payload.pop(digest_field, None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_history(
    history: object,
    current: str,
    initial: str,
    transitions: dict[str, set[str]],
    history_origin: str,
    label: str,
) -> None:
    if not isinstance(history, list) or not history or not all(isinstance(item, str) for item in history):
        fail(f"{label} must be a non-empty array of states")
    if history[-1] != current:
        fail(f"{label} must end with current status {current!r}")
    if history_origin == "native" and history[0] != initial:
        fail(f"{label} must start with {initial!r}")
    for before, after in zip(history, history[1:]):
        if before not in transitions or after not in transitions[before]:
            fail(f"{label} contains invalid transition {before!r} -> {after!r}")


def validate(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"state file does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")

    if not isinstance(state, dict):
        fail("top-level state must be an object")
    schema_version = state.get("schema_version")
    if schema_version not in {5, 6}:
        fail("schema_version must be 5 or 6")
    code_only = schema_version == 6
    if code_only:
        if state.get("archive_mode") != CODE_ONLY_ARCHIVE_MODE:
            fail("schema_version 6 requires archive_mode='code_only'")
    migration = state.get("migration")
    if not isinstance(migration, dict):
        fail("migration must be an object")
    source_schema = migration.get("source_schema")
    if source_schema is not None and source_schema not in {1, 2, 3, 4}:
        fail("migration.source_schema must be null or 1-4")
    if not isinstance(migration.get("legacy_goal"), bool):
        fail("migration.legacy_goal must be boolean")
    legacy_task_ids = validate_string_list(
        migration.get("legacy_task_ids"), "migration.legacy_task_ids"
    )
    if len(legacy_task_ids) != len(set(legacy_task_ids)):
        fail("migration.legacy_task_ids must be unique")
    has_legacy_entities = migration["legacy_goal"] or bool(legacy_task_ids)
    if has_legacy_entities != (source_schema is not None):
        fail("migration.source_schema must be set exactly when legacy entities are registered")

    layout = state.get("layout")
    if not isinstance(layout, dict):
        fail("layout must be an object; migrate older v5 fixed-layout state first")
    layout_origin = layout.get("origin")
    if layout_origin not in {"goal_scoped", "legacy_fixed"}:
        fail("layout.origin must be 'goal_scoped' or 'legacy_fixed'")
    delivery_root = canonical_relative_path(layout.get("delivery_root"), "layout.delivery_root")
    if delivery_root != DEFAULT_DELIVERY_ROOT:
        fail(f"layout.delivery_root must be {DEFAULT_DELIVERY_ROOT!r}")
    declared_goal_root = canonical_relative_path(layout.get("goal_root"), "layout.goal_root")
    legacy_document_paths = validate_string_list(
        layout.get("legacy_document_paths"), "layout.legacy_document_paths"
    )
    legacy_review_artifacts = validate_string_list(
        layout.get("legacy_review_artifacts"), "layout.legacy_review_artifacts"
    )
    for label, paths in (
        ("layout.legacy_document_paths", legacy_document_paths),
        ("layout.legacy_review_artifacts", legacy_review_artifacts),
    ):
        if len(paths) != len(set(paths)):
            fail(f"{label} must be unique")
        for legacy_path in paths:
            canonical_relative_path(legacy_path, label)
            require_under_goal_root(legacy_path, declared_goal_root, label)
    if layout_origin == "goal_scoped" and (legacy_document_paths or legacy_review_artifacts):
        fail("goal_scoped layout cannot declare legacy path exemptions")

    goal = state.get("goal")
    features = state.get("features")
    tasks = state.get("tasks")
    if not isinstance(goal, dict):
        fail("goal must be an object")
    if not isinstance(features, list):
        fail("features must be an array")
    if not isinstance(tasks, list) or not tasks:
        fail("tasks must be a non-empty array")

    goal_id = goal.get("id")
    if not isinstance(goal_id, str) or re.fullmatch(r"GOAL-[A-Za-z0-9._-]+", goal_id) is None:
        fail("goal.id must use the GOAL- prefix")
    require_string(goal.get("title"), "goal.title")
    goal_status = goal.get("status")
    if goal_status not in GOAL_STATES:
        fail(f"invalid goal status: {goal_status!r}")
    goal_history_origin = goal.get("history_origin")
    if goal_history_origin not in {"native", "legacy"}:
        fail("goal.history_origin must be 'native' or 'legacy'")
    if (goal_history_origin == "legacy") != migration["legacy_goal"]:
        fail("goal.history_origin must match migration.legacy_goal")
    goal_legacy_snapshot = goal.get("legacy_snapshot")
    if goal_history_origin == "legacy" and not isinstance(goal_legacy_snapshot, dict):
        fail("migrated Goal requires legacy_snapshot")
    if goal_history_origin == "native" and goal_legacy_snapshot is not None:
        fail("native Goal cannot contain legacy_snapshot")
    validate_history(
        goal.get("status_history"), goal_status, "awaiting_plan_approval",
        GOAL_TRANSITIONS, goal_history_origin, "goal.status_history"
    )
    if not isinstance(goal.get("plan_approved"), bool):
        fail("goal.plan_approved must be boolean")
    if not isinstance(goal.get("human_gate"), bool):
        fail("goal.human_gate must be boolean")
    if goal.get("document_mode") not in {"small", "decomposed"}:
        fail("goal.document_mode must be 'small' or 'decomposed'")
    state_path = canonical_relative_path(goal.get("state_path"), "goal.state_path")
    goal_root = goal_root_from_state_path(state_path)
    if goal_root != declared_goal_root:
        fail("layout.goal_root must equal the parent of goal.state_path")
    plan_path = canonical_relative_path(goal.get("plan_path"), "goal.plan_path")
    if plan_path != f"{goal_root}/plan.md":
        fail("goal.plan_path must be plan.md inside the Goal root")
    if layout_origin == "goal_scoped":
        if PurePosixPath(goal_root).parent.as_posix() != delivery_root:
            fail("goal_scoped layout must place the Goal directly under docs/delivery")
        goal_dir_name = PurePosixPath(goal_root).name
        expected_prefix = f"{goal_id.lower()}-"
        slug = goal_dir_name[len(expected_prefix):] if goal_dir_name.startswith(expected_prefix) else ""
        if (
            state_path != state_path.lower()
            or goal_root == "docs/delivery"
            or not goal_dir_name.startswith(expected_prefix)
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is None
        ):
            fail(
                "new Goal state_path must use a lowercase Goal-scoped directory "
                f"named {goal_id.lower()}-<slug>"
            )
    elif goal_root != delivery_root or state_path != LEGACY_FIXED_STATE_PATH:
        fail("legacy_fixed layout must use docs/delivery/state.json")
    acceptance_evidence = validate_string_list(
        goal.get("acceptance_evidence"), "goal.acceptance_evidence"
    )
    acceptance_files = validate_string_list(goal.get("acceptance_files"), "goal.acceptance_files")
    for acceptance_file in acceptance_files:
        canonical_relative_path(acceptance_file, "goal.acceptance_files")
        validate_delivery_file_ownership(
            acceptance_file, delivery_root, goal_root, layout_origin, "goal.acceptance_files"
        )
    goal_legacy_gaps = validate_string_list(goal.get("legacy_gaps"), "goal.legacy_gaps")
    legacy_previous_status = goal.get("legacy_previous_status")
    if legacy_previous_status is not None and (
        goal_history_origin != "legacy" or legacy_previous_status not in GOAL_STATES
    ):
        fail("goal.legacy_previous_status is only valid for a migrated Goal")
    if goal_history_origin == "native" and goal_legacy_gaps:
        fail("native Goal cannot contain legacy_gaps")
    if goal_legacy_gaps and goal_status != "blocked":
        fail("Goal with legacy_gaps must be blocked")
    if goal_status == "awaiting_plan_approval" and goal["plan_approved"]:
        fail("awaiting_plan_approval requires plan_approved=false")
    if goal_status in {"in_progress", "awaiting_acceptance", "accepted"} and not goal["plan_approved"]:
        fail(f"{goal_status} requires plan_approved=true")
    if goal_status in {"awaiting_acceptance", "accepted"} and not goal["human_gate"]:
        fail(f"{goal_status} requires human_gate=true")
    if goal_status == "accepted" and not acceptance_evidence:
        fail("accepted requires non-empty human acceptance evidence")
    acceptance_message = goal.get("acceptance_commit_message")
    acceptance_origin = goal.get("acceptance_origin")
    goal_legacy_digest = goal.get("legacy_v5_digest")
    if goal_status == "accepted":
        if acceptance_origin not in {"native", "legacy"}:
            if not code_only:
                fail("accepted requires acceptance_origin native or legacy")
        if code_only:
            if acceptance_origin is not None or acceptance_message is not None or acceptance_files:
                fail("code_only acceptance is local metadata and cannot declare a Git acceptance archive")
            if goal_legacy_digest is not None:
                fail("code_only Goal cannot set legacy_v5_digest")
        else:
            acceptance_message = require_string(acceptance_message, "goal.acceptance_commit_message")
            if state_path not in acceptance_files:
                fail("accepted requires goal.state_path in acceptance_files")
            if acceptance_origin == "legacy":
                if goal_history_origin != "legacy" or not isinstance(goal_legacy_digest, str):
                    fail("legacy Goal acceptance requires migrated history and legacy_v5_digest")
                if goal_legacy_digest != stable_digest(goal):
                    fail("legacy Goal v5 representation differs from its migration digest")
            elif goal_legacy_digest is not None:
                fail("native Goal acceptance cannot set legacy_v5_digest")
    elif acceptance_origin is not None or acceptance_message is not None or acceptance_files or goal_legacy_digest is not None:
        fail("only accepted Goals may set acceptance commit metadata")
    if goal_status == "blocked":
        require_string(goal.get("blocked_reason"), "goal.blocked_reason")

    feature_ids: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            fail(f"features[{index}] must be an object")
        feature_id = feature.get("id")
        if not isinstance(feature_id, str) or re.fullmatch(r"FEATURE-[A-Za-z0-9._-]+", feature_id) is None:
            fail(f"features[{index}].id must use the FEATURE- prefix")
        if feature_id in feature_ids:
            fail(f"duplicate feature id: {feature_id}")
        feature_ids.add(feature_id)
        require_string(feature.get("title"), f"{feature_id}.title")

    ids: list[str] = []
    active: list[str] = []
    task_by_id: dict[str, dict] = {}
    archive_messages: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            fail(f"tasks[{index}] must be an object")
        task_id = task.get("id")
        if not isinstance(task_id, str) or re.fullmatch(r"TASK-[A-Za-z0-9._-]+", task_id) is None:
            fail(f"tasks[{index}].id must use the TASK- prefix")
        if task_id in task_by_id:
            fail(f"duplicate task id: {task_id}")
        task_by_id[task_id] = task
        ids.append(task_id)
        if (task_id in legacy_task_ids) != (task.get("history_origin") == "legacy"):
            fail(f"{task_id}: history_origin must match migration.legacy_task_ids")
        require_string(task.get("title"), f"{task_id}.title")

        feature_id = task.get("feature_id")
        if feature_id is not None and feature_id not in feature_ids:
            fail(f"{task_id}: feature_id must reference a declared Feature")
        document_path = canonical_relative_path(task.get("document_path"), f"{task_id}.document_path")
        require_under_goal_root(document_path, goal_root, f"{task_id}.document_path")
        if document_path != document_path.lower() and document_path not in legacy_document_paths:
            fail(f"{task_id}.document_path must be lowercase")
        if document_path in legacy_document_paths:
            expected_legacy_document = f"{goal_root}/tasks/{task_id}.md"
            if document_path != expected_legacy_document:
                fail(
                    f"{task_id}.document_path legacy exemption must equal "
                    f"{expected_legacy_document!r}"
                )
        status = task.get("status")
        if status not in TASK_STATES:
            fail(f"{task_id}: invalid status {status!r}")
        history_origin = task.get("history_origin")
        if history_origin not in {"native", "legacy"}:
            fail(f"{task_id}.history_origin must be 'native' or 'legacy'")
        legacy_snapshot = task.get("legacy_snapshot")
        if history_origin == "legacy" and not isinstance(legacy_snapshot, dict):
            fail(f"{task_id}: migrated Task requires legacy_snapshot")
        if history_origin == "native" and legacy_snapshot is not None:
            fail(f"{task_id}: native Task cannot contain legacy_snapshot")
        task_legacy_gaps = validate_string_list(task.get("legacy_gaps"), f"{task_id}.legacy_gaps")
        legacy_previous_status = task.get("legacy_previous_status")
        if legacy_previous_status is not None and (
            history_origin != "legacy" or legacy_previous_status not in TASK_STATES
        ):
            fail(f"{task_id}: legacy_previous_status is only valid for a migrated Task")
        if history_origin == "native" and task_legacy_gaps:
            fail(f"{task_id}: native Task cannot contain legacy_gaps")
        if task_legacy_gaps and status != "blocked":
            fail(f"{task_id}: Task with legacy_gaps must be blocked")
        legacy_archive_commit = task.get("legacy_archive_commit")
        if legacy_archive_commit is not None and (
            history_origin != "legacy"
            or not isinstance(legacy_archive_commit, str)
            or re.fullmatch(r"[0-9a-fA-F]{7,64}", legacy_archive_commit) is None
        ):
            fail(f"{task_id}: legacy_archive_commit must be a Git hash on a migrated Task")
        validate_history(
            task.get("status_history"), status, "planned", TASK_TRANSITIONS,
            history_origin, f"{task_id}.status_history"
        )
        if status in ACTIVE_TASK_STATES:
            active.append(task_id)
        if status == "blocked":
            require_string(task.get("blocked_reason"), f"{task_id}.blocked_reason")

        dependencies = task.get("dependencies")
        if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
            fail(f"{task_id}: dependencies must be an array of task ids")
        for dependency in dependencies:
            if dependency not in ids[:-1]:
                fail(f"{task_id}: dependency {dependency!r} must refer to an earlier Task")

        for field in (
            "validation_evidence", "self_test_evidence", "regression_evidence",
            "review_evidence", "review_artifacts", "archive_files"
        ):
            validate_string_list(task.get(field), f"{task_id}.{field}")
        for artifact in task["review_artifacts"]:
            canonical_relative_path(artifact, f"{task_id}.review_artifacts")
            require_under_goal_root(artifact, goal_root, f"{task_id}.review_artifacts")
            if artifact != artifact.lower() and artifact not in legacy_review_artifacts:
                fail(f"{task_id}.review_artifacts must be lowercase")
        for archive_file in task["archive_files"]:
            canonical_relative_path(archive_file, f"{task_id}.archive_files")
            validate_delivery_file_ownership(
                archive_file, delivery_root, goal_root, layout_origin, f"{task_id}.archive_files"
            )
            if code_only and path_is_within(archive_file, delivery_root):
                fail(f"{task_id}: code_only archive_files cannot include delivery artifacts")
        validate_string_list(task.get("regression_task_ids"), f"{task_id}.regression_task_ids")
        if not isinstance(task.get("review_round"), int) or task["review_round"] < 0:
            fail(f"{task_id}: review_round must be a non-negative integer")

        if status in REVIEWED_TASK_STATES:
            expected_verdict = "FAIL" if status == "review_failed" else "PASS"
            if task.get("review_verdict") != expected_verdict:
                fail(f"{task_id}: {status} requires review_verdict={expected_verdict}")
            if task["review_round"] < 1:
                fail(f"{task_id}: reviewed task requires review_round >= 1")
            validate_string_list(task["review_evidence"], f"{task_id}.review_evidence", required=True)
            review_artifacts = task["review_artifacts"]
            expected_artifacts = []
            for round_number in range(1, task["review_round"] + 1):
                lowercase_artifact = (
                    f"{goal_root}/reviews/{task_id.lower()}/round-{round_number:02d}.md"
                )
                actual_artifact = review_artifacts[round_number - 1] if len(review_artifacts) >= round_number else None
                if actual_artifact in legacy_review_artifacts:
                    expected_legacy_artifact = (
                        f"{goal_root}/reviews/{task_id}/round-{round_number:02d}.md"
                    )
                    if actual_artifact != expected_legacy_artifact:
                        fail(
                            f"{task_id}: legacy review artifact for round {round_number} "
                            f"must equal {expected_legacy_artifact!r}"
                        )
                    expected_artifacts.append(actual_artifact)
                else:
                    expected_artifacts.append(lowercase_artifact)
            if history_origin == "native":
                if review_artifacts != expected_artifacts:
                    fail(f"{task_id}: review_artifacts must equal {expected_artifacts!r}")
                if len(task["review_evidence"]) < task["review_round"]:
                    fail(f"{task_id}: review_evidence must cover every review round")
            elif not review_artifacts:
                fail(f"{task_id}: migrated reviewed task requires review_artifacts")
            for field in ("validation_evidence", "self_test_evidence", "regression_evidence"):
                validate_string_list(task[field], f"{task_id}.{field}", required=True)
            expected_regression_ids = ids[:-1]
            if task["regression_task_ids"] != expected_regression_ids:
                fail(f"{task_id}: regression_task_ids must equal {expected_regression_ids!r}")

        archive_message = task.get("archive_commit_message")
        archive_origin = task.get("archive_origin")
        archive_commit = task.get("archive_commit")
        task_legacy_digest = task.get("legacy_v5_digest")
        if status == "done":
            if archive_origin not in {"native", "legacy"}:
                fail(f"{task_id}: done task requires archive_origin native or legacy")
            archive_message = require_string(archive_message, f"{task_id}.archive_commit_message")
            if (
                layout_origin == "goal_scoped"
                and archive_origin == "native"
                and (goal_id not in archive_message or task_id not in archive_message)
            ):
                fail(f"{task_id}: native Goal-scoped archive message must include {goal_id} and {task_id}")
            if archive_message in archive_messages:
                fail(f"duplicate archive_commit_message: {archive_message!r}")
            archive_messages.add(archive_message)
            if code_only:
                if archive_origin != "native":
                    fail(f"{task_id}: code_only archives must be native")
                if not isinstance(archive_commit, str) or re.fullmatch(r"[0-9a-fA-F]{7,64}", archive_commit) is None:
                    fail(f"{task_id}: code_only done task requires archive_commit Git hash")
                if not task["archive_files"]:
                    fail(f"{task_id}: code_only done task requires archive_files")
                if task_legacy_digest is not None:
                    fail(f"{task_id}: code_only Task cannot set legacy_v5_digest")
            else:
                required_files = {state_path, document_path, *task["review_artifacts"]}
                if not required_files.issubset(set(task["archive_files"])):
                    fail(f"{task_id}: archive_files must include state, Task document, and review artifact")
                if archive_origin == "legacy":
                    if history_origin != "legacy" or not isinstance(task_legacy_digest, str):
                        fail(f"{task_id}: legacy archive requires migrated history and legacy_v5_digest")
                    if task_legacy_digest != stable_digest(task):
                        fail(f"{task_id}: legacy v5 representation differs from its migration digest")
                elif task_legacy_digest is not None:
                    fail(f"{task_id}: native archive cannot set legacy_v5_digest")
                if archive_commit is not None:
                    fail(f"{task_id}: schema_version 5 cannot set archive_commit")
        elif (
            archive_origin is not None or archive_message is not None or task_legacy_digest is not None
            or (code_only and archive_commit is not None)
        ):
            fail(f"{task_id}: only done tasks may set archive_commit_message")
        elif not code_only and archive_commit is not None:
            fail(f"{task_id}: schema_version 5 cannot set archive_commit")

    if goal_status == "accepted" and acceptance_message in archive_messages:
        fail("Goal acceptance commit message must differ from every Task archive message")

    if goal["document_mode"] == "small":
        if len(tasks) != 1 or tasks[0]["document_path"] != plan_path:
            fail("small document mode requires one Task whose document_path equals goal.plan_path")
    else:
        if len(tasks) < 2:
            fail("decomposed document mode requires at least two tasks")
        paths = [task["document_path"] for task in tasks]
        if len(paths) != len(set(paths)) or plan_path in paths:
            fail("decomposed mode requires distinct Task documents separate from goal.plan_path")
        expected_paths = [f"{goal_root}/tasks/{task['id'].lower()}.md" for task in tasks]
        allowed_paths = [
            actual if actual in legacy_document_paths else expected
            for actual, expected in zip(paths, expected_paths)
        ]
        if paths != allowed_paths:
            fail(f"decomposed Task documents must equal {allowed_paths!r}")

    referenced_documents = {task["document_path"] for task in tasks}
    referenced_reviews = {item for task in tasks for item in task["review_artifacts"]}
    if not set(legacy_document_paths).issubset(referenced_documents):
        fail("layout.legacy_document_paths must reference current Task documents")
    if not set(legacy_review_artifacts).issubset(referenced_reviews):
        fail("layout.legacy_review_artifacts must reference current review artifacts")

    if len(active) > 1:
        fail(f"at most one active task is allowed, found: {', '.join(active)}")
    unknown_legacy_ids = sorted(set(legacy_task_ids) - set(task_by_id))
    if unknown_legacy_ids:
        fail(f"migration.legacy_task_ids contains unknown Tasks: {', '.join(unknown_legacy_ids)}")
    if goal_status == "awaiting_plan_approval" and any(
        task["status"] not in {"planned", "blocked"} for task in tasks
    ):
        fail("Tasks cannot start before Goal plan approval")
    if any(task["status"] in ACTIVE_TASK_STATES for task in tasks):
        if not goal["plan_approved"] or goal_status != "in_progress":
            fail("ready or active Tasks require an approved in-progress Goal")
    if any(task["status"] == "done" for task in tasks):
        if not goal["plan_approved"] or goal_status not in {
            "in_progress", "awaiting_acceptance", "accepted", "blocked"
        }:
            fail("completed Tasks require an approved Goal")

    for index, task in enumerate(tasks):
        for dependency in task["dependencies"]:
            if task["status"] in ACTIVE_TASK_STATES | {"done"} and task_by_id[dependency]["status"] != "done":
                fail(f"{task['id']}: active or completed Task has incomplete dependency {dependency}")
        if task["status"] in ACTIVE_TASK_STATES | {"done"}:
            incomplete = [earlier["id"] for earlier in tasks[:index] if earlier["status"] != "done"]
            if incomplete:
                fail(f"{task['id']}: earlier Tasks are incomplete: {', '.join(incomplete)}")

    if goal_status in {"awaiting_acceptance", "accepted"}:
        incomplete = [task["id"] for task in tasks if task["status"] != "done"]
        if incomplete:
            fail(f"{goal_status} requires all tasks done; incomplete: {', '.join(incomplete)}")

    return state


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git command failed: {' '.join(args)}")
    return result.stdout


def validate_git_archives_v5(path: Path, state: dict) -> None:
    if any(task["status"] in ACTIVE_TASK_STATES for task in state["tasks"]):
        fail("--check-git requires no ready or active Task")
    repo = Path(git_output(path.parent, "rev-parse", "--show-toplevel").strip())
    state_rel = path.resolve().relative_to(repo.resolve()).as_posix()
    if state_rel != state["goal"]["state_path"]:
        fail(f"goal.state_path must match actual state path {state_rel!r}")
    log_lines = git_output(repo, "log", "--format=%H%x09%s").splitlines()
    commits = [(line.split("\t", 1)[0], line.split("\t", 1)[1]) for line in log_lines if "\t" in line]

    task_commits: list[tuple[str, str]] = []
    checked_paths: set[str] = set()
    for task in state["tasks"]:
        if task["status"] != "done":
            continue
        message = task["archive_commit_message"]
        if task.get("archive_origin") == "legacy" and message.startswith("legacy-commit:"):
            matches = [message.split(":", 1)[1]]
        else:
            matches = [commit for commit, subject in commits if subject == message]
        if len(matches) != 1:
            fail(f"{task['id']}: expected exactly one Git commit with subject {message!r}")
        commit = matches[0]
        actual_files = set(
            line for line in git_output(repo, "show", "--format=", "--name-only", commit).splitlines() if line
        )
        if task.get("archive_origin") == "native" and actual_files != set(task["archive_files"]):
            fail(f"{task['id']}: Git archive files do not match archive_files")
        canonical_files = {state_rel, task["document_path"], *task["review_artifacts"]}
        for canonical_file in canonical_files:
            git_output(repo, "cat-file", "-e", f"{commit}:{canonical_file}")
        committed_state = json.loads(git_output(repo, "show", f"{commit}:{state_rel}"))
        lookup_id = task["legacy_snapshot"].get("id") if task.get("history_origin") == "legacy" else task["id"]
        committed_task = next((item for item in committed_state.get("tasks", []) if item.get("id") == lookup_id), None)
        if not committed_task or committed_task.get("status") != "done":
            fail(f"{task['id']}: archive commit does not contain the committed done state")
        if task.get("archive_origin") == "legacy":
            normalized_committed_task = dict(committed_task)
            normalized_committed_task.pop("commit", None)
            if normalized_committed_task != task["legacy_snapshot"]:
                fail(f"{task['id']}: legacy Task snapshot differs from its archive commit")
        elif committed_task != task:
            fail(f"{task['id']}: current completed Task differs from its archive commit")
        task_commits.append((task["id"], commit))
        checked_paths.update(task["archive_files"])

    for (earlier_id, earlier_commit), (later_id, later_commit) in zip(task_commits, task_commits[1:]):
        order = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", earlier_commit, later_commit],
            text=True, capture_output=True, check=False,
        )
        if order.returncode != 0:
            fail(f"Task archive order is invalid: {earlier_id} must precede {later_id}")

    goal = state["goal"]
    if goal["status"] == "accepted":
        message = goal["acceptance_commit_message"]
        if goal.get("acceptance_origin") == "legacy" and message.startswith("legacy-commit:"):
            matches = [message.split(":", 1)[1]]
        else:
            matches = [commit for commit, subject in commits if subject == message]
        if len(matches) != 1:
            fail(f"goal: expected exactly one Git commit with subject {message!r}")
        commit = matches[0]
        actual_files = set(
            line for line in git_output(repo, "show", "--format=", "--name-only", commit).splitlines() if line
        )
        if goal.get("acceptance_origin") == "native" and actual_files != set(goal["acceptance_files"]):
            fail("goal: Git acceptance files do not match acceptance_files")
        for acceptance_file in goal["acceptance_files"]:
            git_output(repo, "cat-file", "-e", f"{commit}:{acceptance_file}")
        committed_state = json.loads(git_output(repo, "show", f"{commit}:{state_rel}"))
        if committed_state.get("goal", {}).get("status") != "accepted":
            fail("goal: acceptance commit does not contain accepted state")
        committed_goal = committed_state.get("goal") or committed_state.get("epic")
        if goal.get("acceptance_origin") == "legacy":
            if committed_goal != goal["legacy_snapshot"]:
                fail("goal: legacy Goal snapshot differs from its acceptance commit")
        elif committed_goal != goal:
            fail("goal: current accepted Goal differs from its acceptance commit")
        if task_commits:
            if task_commits[-1][1] == commit:
                fail("Goal acceptance must use a commit after the final Task archive")
            order = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", task_commits[-1][1], commit],
                text=True, capture_output=True, check=False,
            )
            if order.returncode != 0:
                fail("Goal acceptance commit must follow the final Task archive")
        checked_paths.update(goal["acceptance_files"])

    if checked_paths:
        dirty = git_output(
            repo, "status", "--porcelain=v1", "--untracked-files=all", "--", *sorted(checked_paths)
        ).strip()
        if dirty:
            fail(f"archived files have uncommitted changes:\n{dirty}")


def validate_git_archives_v6(path: Path, state: dict) -> None:
    """Verify code-only Task archives while delivery metadata remains local."""
    if any(task["status"] in ACTIVE_TASK_STATES for task in state["tasks"]):
        fail("--check-git requires no ready or active Task")
    repo = Path(git_output(path.parent, "rev-parse", "--show-toplevel").strip())
    state_rel = path.resolve().relative_to(repo.resolve()).as_posix()
    if state_rel != state["goal"]["state_path"]:
        fail(f"goal.state_path must match actual state path {state_rel!r}")

    task_commits: list[tuple[str, str]] = []
    checked_paths: set[str] = set()
    seen_commits: set[str] = set()
    for task in state["tasks"]:
        if task["status"] != "done":
            continue
        commit = git_output(repo, "rev-parse", "--verify", f"{task['archive_commit']}^{{commit}}").strip()
        if commit in seen_commits:
            fail(f"{task['id']}: archive_commit is reused by another Task")
        seen_commits.add(commit)
        reachable = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, "HEAD"],
            text=True, capture_output=True, check=False,
        )
        if reachable.returncode != 0:
            fail(f"{task['id']}: archive_commit must be reachable from HEAD")
        subject = git_output(repo, "show", "-s", "--format=%s", commit).strip()
        if subject != task["archive_commit_message"]:
            fail(f"{task['id']}: archive_commit subject does not match archive_commit_message")
        actual_files = set(
            line for line in git_output(repo, "show", "--format=", "--name-only", commit).splitlines() if line
        )
        if actual_files != set(task["archive_files"]):
            fail(f"{task['id']}: Git archive files do not match archive_files")
        if any(path_is_within(file, DEFAULT_DELIVERY_ROOT) for file in actual_files):
            fail(f"{task['id']}: code_only archive unexpectedly contains delivery artifacts")
        base_commit = task.get("base_commit")
        if isinstance(base_commit, str) and base_commit:
            result = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", base_commit, commit],
                text=True, capture_output=True, check=False,
            )
            if result.returncode != 0:
                fail(f"{task['id']}: archive_commit must descend from base_commit")
        task_commits.append((task["id"], commit))
        checked_paths.update(task["archive_files"])

    for (earlier_id, earlier_commit), (later_id, later_commit) in zip(task_commits, task_commits[1:]):
        result = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", earlier_commit, later_commit],
            text=True, capture_output=True, check=False,
        )
        if result.returncode != 0:
            fail(f"Task archive order is invalid: {earlier_id} must precede {later_id}")

    if checked_paths:
        dirty = git_output(
            repo, "status", "--porcelain=v1", "--untracked-files=all", "--", *sorted(checked_paths)
        ).strip()
        if dirty:
            fail(f"archived code files have uncommitted changes:\n{dirty}")


def validate_git_archives(path: Path, state: dict) -> None:
    if state.get("schema_version") == 6:
        validate_git_archives_v6(path, state)
        return
    validate_git_archives_v5(path, state)


def main() -> int:
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--check-git"):
        print("usage: validate_delivery_state.py <state.json> [--check-git]", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        state = validate(path)
        if len(sys.argv) == 3:
            validate_git_archives(path, state)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    suffix = " with Git archives" if len(sys.argv) == 3 else ""
    print(f"VALID{suffix}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
