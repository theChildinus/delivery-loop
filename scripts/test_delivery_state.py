#!/usr/bin/env python3
"""Focused regression tests for delivery-loop state and Git archive validation."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import migrate_delivery_state as migrator
import validate_delivery_state as validator


ROOT = Path(__file__).resolve().parents[1]


class DeliveryStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = json.loads((ROOT / "assets/state-template.json").read_text())
        # Existing regression coverage is the frozen audited v5 contract.
        self.base["schema_version"] = 5
        self.base.pop("archive_mode")
        self.base["tasks"][0].pop("archive_commit")

    def assert_invalid(self, state: dict, text: str) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(state, handle)
            handle.flush()
            with self.assertRaisesRegex(ValueError, text):
                validator.validate(Path(handle.name))

    @staticmethod
    def goal_root(state: dict) -> str:
        return str(Path(state["goal"]["state_path"]).parent).replace("\\", "/")

    def review_path(self, state: dict, task_id: str = "TASK-001", round_number: int = 1) -> str:
        return f"{self.goal_root(state)}/reviews/{task_id.lower()}/round-{round_number:02d}.md"

    @staticmethod
    def use_legacy_fixed_layout(state: dict) -> dict:
        state["layout"] = {
            "origin": "legacy_fixed",
            "delivery_root": "docs/delivery",
            "goal_root": "docs/delivery",
            "legacy_document_paths": [],
            "legacy_review_artifacts": [],
        }
        state["goal"]["state_path"] = "docs/delivery/state.json"
        state["goal"]["plan_path"] = "docs/delivery/plan.md"
        if state["goal"]["document_mode"] == "small":
            state["tasks"][0]["document_path"] = "docs/delivery/plan.md"
        return state

    def reviewed_task(self, done: bool = False) -> dict:
        state = copy.deepcopy(self.base)
        state["goal"].update(
            status="in_progress",
            status_history=["awaiting_plan_approval", "in_progress"],
            plan_approved=True,
        )
        task = state["tasks"][0]
        task.update(
            status="done" if done else "review_passed",
            status_history=["planned", "ready", "in_progress", "review_passed"] + (["done"] if done else []),
            review_round=1,
            review_verdict="PASS",
            review_artifacts=[self.review_path(state)],
            review_evidence=["PASS"],
            self_test_evidence=["focused test passed"],
            regression_evidence=["baseline passed"],
            validation_evidence=["AC-001 passed"],
        )
        if done:
            task["archive_origin"] = "native"
            task["archive_commit_message"] = "GOAL-001 TASK-001: complete change"
            task["archive_files"] = [
                state["goal"]["state_path"],
                state["goal"]["plan_path"],
                self.review_path(state),
                "src/change.txt",
            ]
        return state

    def test_template_is_valid(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(self.base, handle)
            handle.flush()
            validator.validate(Path(handle.name))

    def test_generated_document_paths_are_lowercase(self) -> None:
        skill_text = (ROOT / "SKILL.md").read_text()
        for legacy_name in ("PRD.md", "DESIGN.md", "tasks/TASK-", "reviews/TASK-"):
            self.assertNotIn(legacy_name, skill_text)
        state_path = self.base["goal"]["state_path"]
        plan_path = self.base["goal"]["plan_path"]
        document_path = self.base["tasks"][0]["document_path"]
        self.assertEqual(state_path.lower(), state_path)
        self.assertEqual(plan_path.lower(), plan_path)
        self.assertEqual(document_path.lower(), document_path)

    def test_legacy_fixed_v5_layout_remains_valid(self) -> None:
        state = self.use_legacy_fixed_layout(copy.deepcopy(self.base))
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(state, handle)
            handle.flush()
            validator.validate(Path(handle.name))

    def test_pre_layout_v5_is_upgraded_with_explicit_provenance(self) -> None:
        state = self.use_legacy_fixed_layout(copy.deepcopy(self.base))
        state.pop("layout")
        state["goal"]["document_mode"] = "decomposed"
        root = "docs/delivery"
        state["tasks"][0]["document_path"] = f"{root}/tasks/TASK-001.md"
        state["tasks"][0]["review_artifacts"] = [
            f"{root}/reviews/TASK-001/round-01.md"
        ]
        second = copy.deepcopy(state["tasks"][0])
        second.update(id="TASK-002", document_path=f"{root}/tasks/task-002.md", review_artifacts=[])
        state["tasks"].append(second)
        upgraded = migrator.migrate(state)
        self.assertEqual("legacy_fixed", upgraded["layout"]["origin"])
        self.assertEqual(
            [f"{root}/tasks/TASK-001.md"], upgraded["layout"]["legacy_document_paths"]
        )
        self.assertEqual(
            [f"{root}/reviews/TASK-001/round-01.md"],
            upgraded["layout"]["legacy_review_artifacts"],
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(upgraded, handle)
            handle.flush()
            validator.validate(Path(handle.name))

    def test_legacy_review_rounds_can_continue_with_lowercase_paths(self) -> None:
        state = self.use_legacy_fixed_layout(self.reviewed_task())
        task = state["tasks"][0]
        task["review_round"] = 2
        task["review_artifacts"] = [
            "docs/delivery/reviews/TASK-001/round-01.md",
            "docs/delivery/reviews/task-001/round-02.md",
        ]
        task["review_evidence"] = ["round 1", "round 2"]
        state["layout"]["legacy_review_artifacts"] = [task["review_artifacts"][0]]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(state, handle)
            handle.flush()
            validator.validate(Path(handle.name))

    def test_goal_scoped_archive_cannot_include_another_goal(self) -> None:
        state = self.reviewed_task(done=True)
        state["tasks"][0]["archive_files"].append(
            "docs/delivery/goal-000-accepted/state.json"
        )
        self.assert_invalid(state, "another Goal's delivery artifacts")

    def test_legacy_fixed_archive_cannot_include_goal_name_with_underscore(self) -> None:
        state = self.use_legacy_fixed_layout(self.reviewed_task(done=True))
        state["tasks"][0]["archive_files"] = [
            "docs/delivery/state.json",
            "docs/delivery/plan.md",
            "docs/delivery/reviews/task-001/round-01.md",
            "docs/delivery/goal-a_b-accepted/state.json",
        ]
        self.assert_invalid(state, "Goal-scoped delivery directory")

    def test_legacy_fixed_acceptance_cannot_include_goal_name_with_dot(self) -> None:
        state = self.use_legacy_fixed_layout(self.reviewed_task(done=True))
        state["goal"].update(
            status="accepted",
            status_history=[
                "awaiting_plan_approval", "in_progress", "awaiting_acceptance", "accepted"
            ],
            acceptance_evidence=["User accepted"],
            acceptance_origin="native",
            acceptance_commit_message="chore(delivery): accept GOAL-001",
            acceptance_files=[
                "docs/delivery/state.json",
                "docs/delivery/goal-a.b-accepted/state.json",
            ],
        )
        self.assert_invalid(state, "Goal-scoped delivery directory")

    def test_legacy_document_provenance_must_match_task_id(self) -> None:
        state = self.use_legacy_fixed_layout(copy.deepcopy(self.base))
        state["goal"]["document_mode"] = "decomposed"
        state["tasks"][0]["document_path"] = "docs/delivery/tasks/TASK-999.md"
        second = copy.deepcopy(state["tasks"][0])
        second.update(id="TASK-002", document_path="docs/delivery/tasks/task-002.md")
        state["tasks"].append(second)
        state["layout"]["legacy_document_paths"] = [state["tasks"][0]["document_path"]]
        self.assert_invalid(state, "legacy exemption must equal")

    def test_legacy_review_provenance_must_match_task_and_round(self) -> None:
        state = self.use_legacy_fixed_layout(self.reviewed_task())
        task = state["tasks"][0]
        task["review_artifacts"] = ["docs/delivery/reviews/TASK-999/round-42.md"]
        state["layout"]["legacy_review_artifacts"] = list(task["review_artifacts"])
        self.assert_invalid(state, "legacy review artifact for round 1")

    def test_goal_scoped_state_is_anchored_under_docs_delivery(self) -> None:
        state = copy.deepcopy(self.base)
        state["layout"]["delivery_root"] = "tmp"
        state["layout"]["goal_root"] = "tmp/goal-001-escape"
        state["goal"]["state_path"] = "tmp/goal-001-escape/state.json"
        state["goal"]["plan_path"] = "tmp/goal-001-escape/plan.md"
        state["tasks"][0]["document_path"] = "tmp/goal-001-escape/plan.md"
        self.assert_invalid(state, "must be 'docs/delivery'")

    def test_new_goal_directory_must_match_goal_id_and_slug(self) -> None:
        state = copy.deepcopy(self.base)
        state["layout"]["goal_root"] = "docs/delivery/unrelated"
        state["goal"]["state_path"] = "docs/delivery/unrelated/state.json"
        state["goal"]["plan_path"] = "docs/delivery/unrelated/plan.md"
        state["tasks"][0]["document_path"] = "docs/delivery/unrelated/plan.md"
        self.assert_invalid(state, "goal-001-<slug>")

    def test_new_goal_rejects_uppercase_task_document_path(self) -> None:
        state = copy.deepcopy(self.base)
        root = self.goal_root(state)
        state["goal"]["document_mode"] = "decomposed"
        state["tasks"][0]["document_path"] = f"{root}/tasks/TASK-001.md"
        second = copy.deepcopy(state["tasks"][0])
        second.update(id="TASK-002", document_path=f"{root}/tasks/task-002.md")
        state["tasks"].append(second)
        self.assert_invalid(state, "document_path must be lowercase")

    def test_new_goal_archive_message_must_include_goal_and_task_ids(self) -> None:
        state = self.reviewed_task(done=True)
        state["tasks"][0]["archive_commit_message"] = "feat: complete change"
        self.assert_invalid(state, "must include GOAL-001 and TASK-001")

    def test_archive_files_reject_parent_traversal(self) -> None:
        state = self.reviewed_task(done=True)
        state["tasks"][0]["archive_files"].append("../outside.txt")
        self.assert_invalid(state, "repository-relative POSIX path")

    def test_plan_gate_cannot_be_bypassed(self) -> None:
        state = copy.deepcopy(self.base)
        state["tasks"][0].update(status="ready", status_history=["planned", "ready"])
        self.assert_invalid(state, "before Goal plan approval")

    def test_acceptance_requires_human_evidence(self) -> None:
        state = self.reviewed_task(done=True)
        state["goal"].update(
            status="accepted",
            status_history=["awaiting_plan_approval", "in_progress", "awaiting_acceptance", "accepted"],
        )
        self.assert_invalid(state, "human acceptance evidence")

    def test_acceptance_message_cannot_reuse_task_archive_message(self) -> None:
        state = self.reviewed_task(done=True)
        state["goal"].update(
            status="accepted",
            status_history=["awaiting_plan_approval", "in_progress", "awaiting_acceptance", "accepted"],
            acceptance_evidence=["User accepted"],
            acceptance_origin="native",
            acceptance_commit_message="GOAL-001 TASK-001: complete change",
            acceptance_files=[state["goal"]["state_path"]],
        )
        self.assert_invalid(state, "must differ")

    def test_review_failed_requires_review_evidence(self) -> None:
        state = copy.deepcopy(self.base)
        state["goal"].update(
            status="in_progress", status_history=["awaiting_plan_approval", "in_progress"], plan_approved=True
        )
        state["tasks"][0].update(
            status="review_failed",
            status_history=["planned", "ready", "in_progress", "review_failed"],
        )
        self.assert_invalid(state, "review_verdict=FAIL")

    def test_forward_dependency_is_rejected(self) -> None:
        state = copy.deepcopy(self.base)
        root = self.goal_root(state)
        state["goal"]["document_mode"] = "decomposed"
        state["tasks"][0]["document_path"] = f"{root}/tasks/task-001.md"
        second = copy.deepcopy(state["tasks"][0])
        second.update(id="TASK-002", document_path=f"{root}/tasks/task-002.md")
        state["tasks"][0]["dependencies"] = ["TASK-002"]
        state["tasks"].append(second)
        self.assert_invalid(state, "must refer to an earlier Task")

    def test_status_skip_is_rejected(self) -> None:
        state = self.reviewed_task(done=True)
        state["tasks"][0]["status_history"] = ["planned", "done"]
        self.assert_invalid(state, "invalid transition")

    def test_legacy_origin_cannot_be_claimed_by_native_task(self) -> None:
        state = copy.deepcopy(self.base)
        state["tasks"][0]["history_origin"] = "legacy"
        self.assert_invalid(state, "migration.legacy_task_ids")

    def test_null_evidence_is_rejected(self) -> None:
        state = self.reviewed_task()
        state["tasks"][0]["review_evidence"] = [None]
        self.assert_invalid(state, "non-empty strings")

    def test_non_object_state_is_rejected_cleanly(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump([], handle)
            handle.flush()
            with self.assertRaisesRegex(ValueError, "top-level state"):
                validator.validate(Path(handle.name))

    def test_feature_reference_must_be_declared(self) -> None:
        state = copy.deepcopy(self.base)
        state["tasks"][0]["feature_id"] = "FEATURE-login"
        self.assert_invalid(state, "declared Feature")

    def test_git_archive_is_verified_without_persisting_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            state = self.reviewed_task(done=True)
            state_path = state["goal"]["state_path"]
            plan_path = state["goal"]["plan_path"]
            review_path = self.review_path(state)
            files = {
                state_path: json.dumps(state, indent=2) + "\n",
                plan_path: "# Plan\n",
                review_path: "# Review\n\nVerdict: PASS\n",
                "src/change.txt": "implemented\n",
            }
            for relative, content in files.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Delivery Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "delivery@example.test"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "--", *files], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", state["tasks"][0]["archive_commit_message"]], check=True
            )
            validated = validator.validate(repo / state_path)
            validator.validate_git_archives(repo / state_path, validated)

            state["goal"].update(
                status="accepted",
                status_history=[
                    "awaiting_plan_approval", "in_progress", "awaiting_acceptance", "accepted"
                ],
                acceptance_evidence=["User accepted the Goal"],
                acceptance_origin="native",
                acceptance_commit_message="chore(delivery): accept GOAL-001",
                acceptance_files=[state_path],
            )
            (repo / state_path).write_text(json.dumps(state, indent=2) + "\n")
            subprocess.run(["git", "-C", str(repo), "add", "--", state_path], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "chore(delivery): accept GOAL-001"],
                check=True,
            )
            accepted = validator.validate(repo / state_path)
            validator.validate_git_archives(repo / state_path, accepted)

            (repo / "src/change.txt").write_text("dirty after archive\n")
            with self.assertRaisesRegex(ValueError, "uncommitted changes"):
                validator.validate_git_archives(repo / state_path, accepted)
            (repo / "src/change.txt").write_text("implemented\n")

            rewritten = copy.deepcopy(state)
            rewritten["tasks"][0]["review_evidence"] = ["rewritten after archive"]
            (repo / state_path).write_text(json.dumps(rewritten, indent=2) + "\n")
            subprocess.run(["git", "-C", str(repo), "add", "--", state_path], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "rewrite old evidence"], check=True)
            rewritten_state = validator.validate(repo / state_path)
            with self.assertRaisesRegex(ValueError, "differs from its archive commit"):
                validator.validate_git_archives(repo / state_path, rewritten_state)

    def test_archive_commit_cannot_delete_canonical_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            initial = copy.deepcopy(self.base)
            initial = self.use_legacy_fixed_layout(initial)
            initial_files = {
                "docs/delivery/state.json": json.dumps(initial, indent=2) + "\n",
                "docs/delivery/plan.md": "# Plan\n",
                "docs/delivery/reviews/TASK-001/round-01.md": "# Pending review\n",
            }
            for relative, content in initial_files.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Delivery Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "delivery@example.test"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial plan"], check=True)

            done = self.use_legacy_fixed_layout(self.reviewed_task(done=True))
            done["tasks"][0]["review_artifacts"] = ["docs/delivery/reviews/TASK-001/round-01.md"]
            done["layout"]["legacy_review_artifacts"] = list(done["tasks"][0]["review_artifacts"])
            done["tasks"][0]["archive_files"] = list(initial_files)
            (repo / "docs/delivery/state.json").write_text(json.dumps(done, indent=2) + "\n")
            (repo / "docs/delivery/plan.md").unlink()
            (repo / "docs/delivery/reviews/TASK-001/round-01.md").unlink()
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "feat: complete TASK-001"], check=True
            )
            validated = validator.validate(repo / "docs/delivery/state.json")
            with self.assertRaises(ValueError):
                validator.validate_git_archives(repo / "docs/delivery/state.json", validated)

    def test_migrated_v4_task_archive_uses_legacy_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            archive_files = [
                "docs/delivery/state.json",
                "docs/delivery/plan.md",
                "docs/delivery/reviews/TASK-001/round-01.md",
            ]
            legacy = {
                "schema_version": 4,
                "goal": {
                    "id": "GOAL-001", "title": "Legacy", "status": "in_progress",
                    "plan_approved": True, "human_gate": True,
                    "plan_path": "docs/delivery/plan.md", "document_mode": "small",
                    "acceptance_evidence": [],
                },
                "tasks": [{
                    "id": "TASK-001", "feature_id": None, "title": "Legacy done Task",
                    "status": "done", "dependencies": [], "document_path": "docs/delivery/plan.md",
                    "review_round": 1, "review_verdict": "PASS",
                    "review_artifact": "docs/delivery/reviews/TASK-001/round-01.md",
                    "review_evidence": ["PASS"], "self_test_evidence": ["self passed"],
                    "regression_task_ids": [], "regression_evidence": ["baseline passed"],
                    "validation_evidence": ["AC passed"], "archive_files": archive_files,
                    "commit": None, "blocked_reason": None,
                }],
            }
            files = {
                "docs/delivery/state.json": json.dumps(legacy, indent=2) + "\n",
                "docs/delivery/plan.md": "# Legacy plan\n",
                "docs/delivery/reviews/TASK-001/round-01.md": "# Legacy review\n",
            }
            for relative, content in files.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Delivery Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "delivery@example.test"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "legacy task archive"], check=True)
            legacy_hash = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True, capture_output=True, check=True
            ).stdout.strip()
            legacy["tasks"][0]["commit"] = legacy_hash
            migrated = migrator.migrate(legacy)
            self.assertEqual("done", migrated["tasks"][0]["status"])
            self.assertEqual([], migrated["tasks"][0]["legacy_gaps"])
            (repo / "docs/delivery/state.json").write_text(json.dumps(migrated, indent=2) + "\n")
            subprocess.run(["git", "-C", str(repo), "add", "docs/delivery/state.json"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "migrate delivery state"], check=True)
            validated = validator.validate(repo / "docs/delivery/state.json")
            validator.validate_git_archives(repo / "docs/delivery/state.json", validated)

            rewritten = copy.deepcopy(migrated)
            rewritten["tasks"][0]["review_evidence"] = ["rewritten legacy evidence"]
            (repo / "docs/delivery/state.json").write_text(json.dumps(rewritten, indent=2) + "\n")
            subprocess.run(["git", "-C", str(repo), "add", "docs/delivery/state.json"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "rewrite legacy evidence"], check=True)
            with self.assertRaisesRegex(ValueError, "migration digest"):
                validator.validate(repo / "docs/delivery/state.json")

    def test_v4_migration_is_explicitly_marked(self) -> None:
        legacy = copy.deepcopy(self.base)
        legacy["schema_version"] = 4
        legacy.pop("migration")
        legacy["goal"].pop("status_history")
        legacy["goal"].pop("history_origin")
        legacy["goal"].pop("legacy_snapshot")
        legacy["goal"].pop("state_path")
        legacy.pop("features")
        task = legacy["tasks"][0]
        task.pop("status_history")
        task.pop("history_origin")
        task.pop("legacy_snapshot")
        task.pop("review_artifacts")
        task.pop("archive_commit_message")
        task.pop("archive_files")
        task.pop("archive_origin")
        task.pop("legacy_v5_digest")
        task["commit"] = None
        migrated = migrator.migrate(legacy)
        self.assertEqual(5, migrated["schema_version"])
        self.assertEqual(4, migrated["migration"]["source_schema"])
        self.assertEqual(["TASK-001"], migrated["migration"]["legacy_task_ids"])
        self.assertEqual(["planned"], migrated["tasks"][0]["status_history"])
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(migrated, handle)
            handle.flush()
            validator.validate(Path(handle.name))

    def test_migration_blocks_done_task_when_evidence_is_missing(self) -> None:
        legacy = {
            "schema_version": 4,
            "goal": {
                "id": "GOAL-001", "title": "Legacy", "status": "in_progress",
                "plan_approved": True, "human_gate": True,
                "plan_path": "docs/delivery/plan.md", "document_mode": "small",
                "acceptance_evidence": [],
            },
            "tasks": [{
                "id": "TASK-001", "feature_id": None, "title": "Legacy done Task",
                "status": "done", "dependencies": [], "document_path": "docs/delivery/plan.md",
                "review_round": 0, "review_verdict": None, "review_evidence": [],
                "self_test_evidence": [], "regression_task_ids": [],
                "regression_evidence": [], "validation_evidence": [], "commit": None,
            }],
        }
        migrated = migrator.migrate(legacy)
        task = migrated["tasks"][0]
        self.assertEqual("blocked", task["status"])
        self.assertEqual("done", task["legacy_previous_status"])
        self.assertIn("review_evidence", task["legacy_gaps"])
        self.assertEqual([], task["review_evidence"])
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(migrated, handle)
            handle.flush()
            validator.validate(Path(handle.name))

    def test_v1_multi_task_migration_infers_decomposed_documents(self) -> None:
        legacy = {
            "schema_version": 1,
            "epic": {
                "id": "EPIC-001",
                "title": "Legacy Goal",
                "status": "awaiting_plan_approval",
                "plan_approved": False,
                "human_gate": True,
                "acceptance_evidence": [],
            },
            "tasks": [
                {"id": "1", "story_id": "STORY-login", "title": "One", "status": "planned", "dependencies": []},
                {"id": "two", "story_id": "STORY-login", "title": "Two", "status": "planned", "dependencies": ["1"]},
            ],
        }
        migrated = migrator.migrate(legacy)
        self.assertEqual("decomposed", migrated["goal"]["document_mode"])
        self.assertEqual("TASK-1", migrated["tasks"][0]["id"])
        self.assertEqual("TASK-two", migrated["tasks"][1]["id"])
        self.assertEqual(["TASK-1"], migrated["tasks"][1]["dependencies"])
        self.assertEqual("docs/delivery/tasks/task-1.md", migrated["tasks"][0]["document_path"])
        self.assertEqual("FEATURE-login", migrated["tasks"][0]["feature_id"])
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(migrated, handle)
            handle.flush()
            validator.validate(Path(handle.name))


if __name__ == "__main__":
    unittest.main()
