# Subagent handoff

Use the smallest packet that lets the agent work independently.

## Worker

- Current `execution_context` and checkpoint: active Task, next action, and owner.
- Current Task document and only the relevant design/PRD sections.
- Applicable repository instructions, affected files, and allowed scope.
- Self-test and cumulative-regression commands.
- On a repair round: the newest FAIL artifact and current Task diff only.

Require changed files, commands with exit results, residual risks, and one recommended
next action. If progress is impossible or evidence is missing, require the exact
blocker and the decision/evidence needed to continue. The Worker never commits,
pushes, edits state, or writes review artifacts.

## Reviewer

- Current `execution_context` and checkpoint: active Task, next action, and owner.
- Acceptance criteria, exact base commit and diff scope.
- Concise Worker test evidence and required cumulative scope.
- `review-rubric.md` and, when applicable, `semantic-invariants.md`.

Require evidence-backed PASS or FAIL and one recommended next action only. Do not send
Worker reasoning, unrelated history, or the desired conclusion. The Reviewer does not
edit files.
