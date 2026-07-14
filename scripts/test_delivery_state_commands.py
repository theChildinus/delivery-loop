#!/usr/bin/env python3
"""End-to-end tests for schema-v6 code-only state transitions and recovery."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import validate_delivery_state as validator


ROOT = Path(__file__).resolve().parents[1]
STATE_SCRIPT = ROOT / "scripts" / "delivery_state.py"


class DeliveryStateCommandTests(unittest.TestCase):
    def make_repo(self) -> tuple[Path, Path, str]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repo = Path(directory.name)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Delivery Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "delivery@example.test"], check=True)
        (repo / "src").mkdir()
        (repo / "src" / "feature.txt").write_text("before\n")
        subprocess.run(["git", "-C", str(repo), "add", "src/feature.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "baseline"], check=True)
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True, capture_output=True, check=True
        ).stdout.strip()
        state = json.loads((ROOT / "assets" / "state-template.json").read_text())
        root = "docs/delivery/goal-001-demo"
        state["layout"]["goal_root"] = root
        state["goal"]["state_path"] = f"{root}/state.json"
        state["goal"]["plan_path"] = f"{root}/plan.md"
        state["tasks"][0]["document_path"] = f"{root}/plan.md"
        state_path = repo / state["goal"]["state_path"]
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        (repo / state["goal"]["plan_path"]).write_text("# Local delivery plan\n")
        return repo, state_path, base

    def invoke(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(STATE_SCRIPT), *args], cwd=repo, text=True,
            capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=True,
        )

    @staticmethod
    def artifact(repo: Path, root: str, verdict: str = "PASS") -> str:
        relative = f"{root}/reviews/task-001/round-01.md"
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Review\n\n- Verdict: {verdict}\n")
        return relative

    def review_args(self, state_path: Path, artifact: str, verdict: str = "PASS") -> list[str]:
        return [
            "record-review", "--state", str(state_path), "--task", "TASK-001",
            "--verdict", verdict, "--artifact", artifact,
            "--evidence", "Reviewer verified AC-001.",
            "--self-test", "Focused test passed.",
            "--regression", "Baseline regression passed.",
            "--validation", "Acceptance criterion has direct evidence.",
        ]

    def commit_code(self, repo: Path) -> str:
        (repo / "src" / "feature.txt").write_text("after\n")
        subprocess.run(["git", "-C", str(repo), "add", "src/feature.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "GOAL-001 TASK-001: add feature"], check=True
        )
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True, capture_output=True, check=True
        ).stdout.strip()

    def test_code_only_archive_is_idempotent_and_excludes_delivery_docs(self) -> None:
        repo, state_path, base = self.make_repo()
        started = self.invoke(repo, "start-task", "--state", str(state_path), "--task", "TASK-001", "--approve-plan")
        self.assertIn("UPDATED", started.stdout)
        self.assertIn("NO-OP", self.invoke(repo, "start-task", "--state", str(state_path), "--task", "TASK-001").stdout)
        state = validator.validate(state_path)
        self.assertEqual(base, state["tasks"][0]["base_commit"])

        artifact = self.artifact(repo, "docs/delivery/goal-001-demo")
        self.invoke(repo, *self.review_args(state_path, artifact))
        self.assertIn("NO-OP", self.invoke(repo, *self.review_args(state_path, artifact)).stdout)
        commit = self.commit_code(repo)
        archive_args = [
            "archive-task", "--state", str(state_path), "--task", "TASK-001", "--commit", commit,
            "--message", "GOAL-001 TASK-001: add feature", "--file", "src/feature.txt",
        ]
        self.invoke(repo, *archive_args)
        self.assertIn("NO-OP", self.invoke(repo, *archive_args).stdout)
        state = validator.validate(state_path)
        validator.validate_git_archives(state_path, state)
        self.assertEqual("awaiting_acceptance", state["goal"]["status"])
        self.assertEqual(commit, state["tasks"][0]["archive_commit"])
        committed_files = subprocess.run(
            ["git", "-C", str(repo), "show", "--format=", "--name-only", commit],
            text=True, capture_output=True, check=True,
        ).stdout.splitlines()
        self.assertEqual(["src/feature.txt"], committed_files)

        self.invoke(repo, "accept-goal", "--state", str(state_path), "--evidence", "User accepted locally.")
        accepted = validator.validate(state_path)
        validator.validate_git_archives(state_path, accepted)
        self.assertEqual("accepted", accepted["goal"]["status"])
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], text=True, capture_output=True, check=True
        ).stdout
        self.assertIn("?? docs/", status)

    def test_recover_records_artifact_then_unique_code_commit(self) -> None:
        repo, state_path, _ = self.make_repo()
        self.invoke(repo, "start-task", "--state", str(state_path), "--task", "TASK-001", "--approve-plan")
        self.artifact(repo, "docs/delivery/goal-001-demo")
        recovered_review = self.invoke(
            repo, "recover", "--state", str(state_path), "--task", "TASK-001",
            "--evidence", "Recovered Reviewer PASS.", "--self-test", "Focused test passed.",
            "--regression", "Baseline regression passed.", "--validation", "Acceptance criterion has direct evidence.",
        )
        self.assertIn("UPDATED", recovered_review.stdout)
        self.commit_code(repo)
        recovered_archive = self.invoke(repo, "recover", "--state", str(state_path), "--task", "TASK-001")
        self.assertIn("UPDATED", recovered_archive.stdout)
        state = validator.validate(state_path)
        validator.validate_git_archives(state_path, state)
        self.assertEqual("done", state["tasks"][0]["status"])


if __name__ == "__main__":
    unittest.main()
