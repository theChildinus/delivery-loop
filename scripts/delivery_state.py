#!/usr/bin/env python3
"""Atomically advance schema-v6 code-only delivery state.

This script intentionally does not create commits, review artifacts, or approvals. It
records those externally-produced facts with idempotent, validated state transitions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import validate_delivery_state as validator


def fail(message: str) -> None:
    raise ValueError(message)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git command failed: {' '.join(args)}")
    return result.stdout.strip()


def repo_for(path: Path) -> Path:
    return Path(git(path.parent, "rev-parse", "--show-toplevel"))


def load(path: Path) -> dict:
    state = validator.validate(path)
    if state.get("schema_version") != 6 or state.get("archive_mode") != validator.CODE_ONLY_ARCHIVE_MODE:
        fail("delivery_state.py supports only schema_version 6 code_only state")
    return state


def task_for(state: dict, task_id: str) -> dict:
    for task in state["tasks"]:
        if task["id"] == task_id:
            return task
    fail(f"unknown Task: {task_id}")


def append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def append_status(entity: dict, status: str) -> None:
    if entity["status"] == status:
        return
    entity["status"] = status
    entity["status_history"].append(status)


def atomic_write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        validator.validate(temporary)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def persist(path: Path, state: dict) -> None:
    atomic_write(path, state)
    print(f"UPDATED: {path}")


def expected_review_path(state: dict, task: dict, round_number: int) -> str:
    root = validator.goal_root_from_state_path(state["goal"]["state_path"])
    return f"{root}/reviews/{task['id'].lower()}/round-{round_number:02d}.md"


def require_evidence(args: argparse.Namespace) -> None:
    for option in ("evidence", "self_test", "regression", "validation"):
        if not getattr(args, option, None):
            fail(f"--{option.replace('_', '-')} is required")


def start_task(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = load(path)
    task = task_for(state, args.task)
    goal = state["goal"]
    if task["status"] == "in_progress":
        print("NO-OP: Task is already in_progress")
        return
    if goal["status"] == "awaiting_plan_approval":
        if not args.approve_plan:
            fail("--approve-plan is required to leave awaiting_plan_approval")
        goal["plan_approved"] = True
        append_status(goal, "in_progress")
    if goal["status"] != "in_progress" or not goal["plan_approved"]:
        fail("Task can start only in an approved in_progress Goal")
    index = state["tasks"].index(task)
    incomplete = [item["id"] for item in state["tasks"][:index] if item["status"] != "done"]
    if incomplete:
        fail(f"earlier Tasks are incomplete: {', '.join(incomplete)}")
    if task["status"] == "planned":
        append_status(task, "ready")
        append_status(task, "in_progress")
        task["base_commit"] = git(repo_for(path), "rev-parse", "HEAD")
    elif task["status"] == "review_failed":
        append_status(task, "in_progress")
    else:
        fail(f"Task cannot start from {task['status']!r}")
    persist(path, state)


def record_review(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = load(path)
    task = task_for(state, args.task)
    require_evidence(args)
    artifact = validator.canonical_relative_path(args.artifact, "--artifact")
    if task["status"] in {"review_failed", "review_passed"}:
        if task["review_verdict"] == args.verdict and artifact == task["review_artifacts"][-1]:
            print("NO-OP: review is already recorded")
            return
        fail("record-review conflicts with an already recorded review")
    expected_round = task["review_round"] + 1
    expected_artifact = expected_review_path(state, task, expected_round)
    if artifact != expected_artifact:
        fail(f"--artifact must be {expected_artifact!r}")
    artifact_file = repo_for(path) / artifact
    if not artifact_file.is_file():
        fail(f"review artifact does not exist: {artifact}")
    content = artifact_file.read_text(encoding="utf-8")
    if re.search(r"^\s*-\s*Verdict:\s*" + re.escape(args.verdict) + r"\s*$", content, re.MULTILINE) is None:
        fail(f"review artifact does not declare Verdict: {args.verdict}")
    if task["status"] != "in_progress":
        fail("record-review requires an in_progress Task")
    task["review_round"] = expected_round
    task["review_verdict"] = args.verdict
    task["review_artifacts"].append(artifact)
    append_once(task["review_evidence"], args.evidence)
    append_once(task["self_test_evidence"], args.self_test)
    append_once(task["regression_evidence"], args.regression)
    append_once(task["validation_evidence"], args.validation)
    append_status(task, "review_passed" if args.verdict == "PASS" else "review_failed")
    persist(path, state)


def archive_task(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = load(path)
    task = task_for(state, args.task)
    repo = repo_for(path)
    commit = git(repo, "rev-parse", "--verify", f"{args.commit}^{{commit}}")
    actual_message = git(repo, "show", "-s", "--format=%s", commit)
    if actual_message != args.message:
        fail("--message must match the commit subject")
    files = sorted(dict.fromkeys(validator.canonical_relative_path(item, "--file") for item in args.file))
    actual_files = sorted(line for line in git(repo, "show", "--format=", "--name-only", commit).splitlines() if line)
    if actual_files != files:
        fail("--file values must exactly match the commit files")
    if any(validator.path_is_within(item, validator.DEFAULT_DELIVERY_ROOT) for item in files):
        fail("code_only archives cannot include docs/delivery artifacts")
    if task["status"] == "done":
        if task["archive_commit"] == commit and task["archive_files"] == files and task["archive_commit_message"] == args.message:
            print("NO-OP: Task archive is already recorded")
            return
        fail("archive-task conflicts with an existing Task archive")
    if task["status"] != "review_passed":
        fail("archive-task requires a review_passed Task")
    task["archive_origin"] = "native"
    task["archive_commit_message"] = args.message
    task["archive_commit"] = commit
    task["archive_files"] = files
    append_status(task, "done")
    if all(item["status"] == "done" for item in state["tasks"]):
        append_status(state["goal"], "awaiting_acceptance")
    persist(path, state)


def accept_goal(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = load(path)
    goal = state["goal"]
    if goal["status"] == "accepted":
        if args.evidence in goal["acceptance_evidence"]:
            print("NO-OP: Goal is already accepted")
            return
        fail("accept-goal conflicts with existing acceptance evidence")
    if goal["status"] != "awaiting_acceptance":
        fail("accept-goal requires awaiting_acceptance")
    append_once(goal["acceptance_evidence"], args.evidence)
    append_status(goal, "accepted")
    persist(path, state)


def recover(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = load(path)
    task = task_for(state, args.task)
    repo = repo_for(path)
    if task["status"] == "in_progress":
        artifact = expected_review_path(state, task, task["review_round"] + 1)
        artifact_file = repo / artifact
        if artifact_file.is_file():
            require_evidence(args)
            content = artifact_file.read_text(encoding="utf-8")
            match = re.search(r"^\s*-\s*Verdict:\s*(PASS|FAIL)\s*$", content, re.MULTILINE)
            if not match:
                fail(f"review artifact lacks a supported verdict: {artifact}")
            args.artifact = artifact
            args.verdict = match.group(1)
            record_review(args)
            return
    if task["status"] == "review_passed":
        base = task.get("base_commit")
        if not isinstance(base, str) or not base:
            fail("recover requires base_commit to locate a code archive")
        prefix = f"{state['goal']['id']} {task['id']}:"
        candidates = []
        for line in git(repo, "log", f"{base}..HEAD", "--format=%H%x09%s").splitlines():
            commit, subject = line.split("\t", 1)
            if subject.startswith(prefix):
                candidates.append((commit, subject))
        if len(candidates) != 1:
            fail("recover found zero or multiple candidate code commits")
        commit, message = candidates[0]
        files = [line for line in git(repo, "show", "--format=", "--name-only", commit).splitlines() if line]
        args.commit = commit
        args.message = message
        args.file = files
        archive_task(args)
        return
    print("NO-OP: no recoverable transition found")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    def state_task(command: str) -> argparse.ArgumentParser:
        item = commands.add_parser(command)
        item.add_argument("--state", required=True)
        item.add_argument("--task", required=True)
        return item
    start = state_task("start-task")
    start.add_argument("--approve-plan", action="store_true")
    review = state_task("record-review")
    review.add_argument("--verdict", choices=("PASS", "FAIL"), required=True)
    review.add_argument("--artifact", required=True)
    review.add_argument("--evidence", required=True)
    review.add_argument("--self-test", required=True)
    review.add_argument("--regression", required=True)
    review.add_argument("--validation", required=True)
    archive = state_task("archive-task")
    archive.add_argument("--commit", required=True)
    archive.add_argument("--message", required=True)
    archive.add_argument("--file", action="append", required=True)
    accept = commands.add_parser("accept-goal")
    accept.add_argument("--state", required=True)
    accept.add_argument("--evidence", required=True)
    recover = state_task("recover")
    recover.add_argument("--evidence")
    recover.add_argument("--self-test")
    recover.add_argument("--regression")
    recover.add_argument("--validation")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        {
            "start-task": start_task,
            "record-review": record_review,
            "archive-task": archive_task,
            "accept-goal": accept_goal,
            "recover": recover,
        }[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"STATE UPDATE FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
