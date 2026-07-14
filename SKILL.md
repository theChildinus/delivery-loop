---
name: delivery-loop
description: Turn an ambiguous software requirement into a clarified PRD, technical design, Goal/optional Feature/Task plan, and a human-gated Worker-Reviewer delivery loop with persistent state. Use when the user asks to develop a feature from requirements, formalize a product discussion into an executable plan, run task-by-task implementation and review, resume a partially completed delivery Goal, or establish a human-gated delivery workflow. Do not use for a one-line edit, a read-only code review, or an already-scoped standalone fix that does not need product decomposition.
---

# Delivery Loop

Turn a product conversation into a resumable, human-gated delivery system. Keep
product decisions in the main task; delegate only bounded implementation and review.

## Non-negotiables

1. Read applicable repository instructions, including `AGENTS.md` and `CLAUDE.md`
   when present; resolve the repository/write scope and preserve unrelated user
   changes.
2. Before a non-trivial write, state the outcome, invariants, non-goals, and evidence
   required for completion.
3. Treat push, PR creation, CI, deployments, database writes, and remote
   configuration as separately approved external mutations.
4. Do not implement until the user explicitly approves the plan. Do not mark a Goal
   accepted without explicit human acceptance.
5. Never use destructive Git cleanup commands.
6. Before implementing every development requirement, isolate it in a newly created
   Git branch or a newly created Git worktree dedicated to that requirement. Record
   the selected branch or worktree in the plan, and do not implement on a pre-existing
   branch or worktree (including the default branch).
7. Do not require, install, or execute helper scripts to run this workflow. Maintain
   delivery state directly in `state.json` using the manual protocol below.

## Artifacts and archive mode

Create one immutable Goal root:

```text
docs/delivery/<goal-id-lower>-<short-lowercase-slug>/
├── prd.md
├── design.md
├── plan.md
├── state.json
├── tasks/task-<nnn>.md        # decomposed mode only
└── reviews/task-<nnn>/round-<nn>.md
```

All generated path segments are lowercase; IDs inside documents/state remain uppercase
(`GOAL-001`, `TASK-001`). Derive paths from `goal.state_path`; never overwrite or
reuse an accepted Goal root. New Goals use `schema_version: 8`, `state_mode: manual`,
and `archive_mode: code_only`: delivery artifacts stay local and code commits contain
only implementation, tests, and required runtime configuration. Never add
`docs/delivery/**` to a code-only commit or edit `.gitignore` on the user's behalf.

Record the dedicated branch and absolute worktree path in `execution_context`. The
plan links to `state.json`; it does not maintain a second copy of live status.

Before creating a Goal, enumerate `docs/delivery/state.json` and
`docs/delivery/*/state.json`; choose an ID and root that do not collide with any
existing Goal, including a blocked or unaccepted one. Copy the relevant assets:
`prd-template.md`, `design-template.md`, `plan-template.md`, `task-template.md`,
`state-template.json`, and `review-template.md`.

- **Small mode:** one independently reviewable commit; `plan.md` is its only Task
  document.
- **Decomposed mode:** one Task document and one local code commit per bounded Task.
  Split when responsibilities, dependencies, or verification cannot remain coherent.

Do not create delivery artifacts for a workflow discussion or preview.

## Plan and human gate

Clarify one decision-relevant question at a time. Resolve user/problem, observable
behavior, acceptance criteria, non-goals, compatibility/data semantics, failure and
rollback behavior, and stopping evidence. Record minor assumptions; stop when the
remaining uncertainty cannot change implementation direction.

Create PRD, design, and plan before implementation. A Goal is one user-verifiable
outcome with one acceptance gate; a Feature is optional grouping; a Task is the
smallest independently reviewable implementation unit. Every Task defines scope,
acceptance criteria, focused self-test, cumulative regression, and intended local
commit. All Tasks in one Goal share its dedicated execution context; create a new Goal
instead of changing branches or worktrees mid-Goal.

For every Task, define both:

- **Self-test:** evidence for this Task's acceptance criteria.
- **Cumulative regression:** evidence that all earlier `done` Tasks still hold. The
  first Task records a stable baseline; use an explicit N/A reason only when no
  prior behavior exists.

Initialize `state.json` with Goal `awaiting_plan_approval`, Tasks `planned` or
`blocked`, and a checkpoint owned by `user` that requests plan approval. Inspect the
complete JSON after writing it: it must be valid JSON, its `goal.state_path` must
name the current Goal root, every `status_history` must end with that entity's current
`status`, and its `execution_context` must identify the active branch or worktree.

Present scope, tradeoffs, validation strategy, and non-goals. Stop for explicit plan
approval.

## Manual state protocol

`state.json` has one interface: **read `checkpoint`, complete its `next_action`, then
record the resulting fact and the next checkpoint.** It is the only live-status source.
Plans and Task documents describe intended work; review artifacts and Git commits are
evidence, not competing status records.

Goal states are `awaiting_plan_approval`, `in_progress`, `awaiting_acceptance`,
`accepted`, and `blocked`. Task states are `planned`, `ready`, `in_progress`,
`review_failed`, `review_passed`, `blocked`, and `done`.

`checkpoint` never repeats a status. It contains exactly one active Task (or `null`),
one `next_owner` (`user`, `orchestrator`, `worker`, or `reviewer`), one imperative
`next_action`, a short `resume_from` evidence pointer, and `updated_at`. At every
non-terminal boundary, update it before ending the turn or handing work to another
agent. `updated_at` is an ISO-8601 UTC timestamp after initialization.

For every manual transition:

1. Read `execution_context`, `checkpoint`, current `state.json`, relevant Git
   history, and review artifact first. Confirm the declared worktree exists and its
   branch matches `execution_context`; otherwise block and ask the user where to
   resume.
2. Create the review artifact or code commit before recording it in state.
3. Update the entity's `status` and append the same new value to `status_history`.
4. Add only direct evidence to evidence lists; preserve prior entries. Update
   `checkpoint` in the same edit.
5. Re-read the whole `state.json` and verify paths, statuses, histories, dependencies,
   checkpoint, and human gates agree.

Apply these transitions exactly:

| Event | Required state and checkpoint update |
| --- | --- |
| Initialize | Goal is `awaiting_plan_approval`, `plan_approved: false`; Tasks are `planned` or `blocked`. Every initially blocked entity has a current `blocked_reason` and one open `block_history` record. Checkpoint is owned by `user` with plan approval as the only next action. |
| Approve and start a Task | Record explicit plan approval, append Goal `in_progress`, and record the selected Task as `ready` then `in_progress`. Set its `base_commit` to current HEAD and list earlier completed Tasks in `regression_task_ids`. Checkpoint owner is `worker`; action is the Task's bounded implementation and evidence. Do not start until all earlier Tasks are `done`. |
| Record review | First create `reviews/<task-id-lower>/round-<nn>.md` with one `PASS` or `FAIL`. Increment `review_round`, append its path, set verdict, and add review/self-test/regression/validation evidence. On PASS set `consecutive_review_failures` to zero and checkpoint owner to `orchestrator` for regression, notice, and archive. On FAIL increment `consecutive_review_failures`. |
| First FAIL | Append `review_failed`; checkpoint owner is `worker` and action is only the reviewer’s bounded corrections. |
| Second consecutive FAIL | Do not create another Worker. Append `review_failed`, then `blocked`; add a `block_history` record naming the two FAIL artifacts. Checkpoint owner is `user` and action requests one explicit decision: refactor, design correction, or Task split. |
| Archive a Task | Only after `review_passed`, commit exactly Task code/test/runtime files. Record exact subject, full hash, and manifest, append `done`, and exclude delivery artifacts. Checkpoint advances to the next planned Task; after the final Task it is owned by `orchestrator` for Goal-level checks. |
| Prepare acceptance | After every Goal acceptance criterion and full regression has direct evidence, append Goal `awaiting_acceptance`. Checkpoint owner is `user`; its action names the evidence to review and requests explicit acceptance. |
| Accept a Goal | Only from `awaiting_acceptance` after explicit human acceptance. Append acceptance evidence and Goal `accepted`; checkpoint has no active Task and says the Goal is complete. |
| Block or resume | Before appending `blocked`, append an open object to `block_history` with `reason`, `blocked_from`, and `blocked_at`, and set the same `blocked_reason`. To resume, update the latest open record with `resumed_to`, `resumed_at`, and direct `resume_evidence`; only then clear `blocked_reason`, append the supported target status, and set one next action. A user-directed resume after the two-FAIL hard stop must name the refactor, design correction, or Task split in `resume_evidence` and resets `consecutive_review_failures` to zero for that new repair cycle. Never overwrite an earlier record. |
| Recover after interruption | Start from `checkpoint`, then reconcile its evidence pointer with Git and review artifacts. Record only uniquely supported facts. If the worktree, evidence, or next action is missing or ambiguous, block and make the checkpoint user-owned with the exact missing decision or evidence. |

## Liveness and interruption rules

- A Worker or Reviewer run is one bounded attempt, not an open-ended background job.
  It must return evidence, a bounded failure, or an explicit external dependency.
- Before every wait, tool retry, handoff, or end of a non-terminal turn, persist a
  checkpoint and report its owner, next action, and missing evidence to the user.
  Never silently poll or imply work will continue without a recorded checkpoint.
- If an attempt cannot produce new evidence, or the same uncertainty reappears, block
  the Task and give the user the smallest decision needed to resume. Do not loop on
  retries, re-reviews, or new Workers.
- A blocked Task can resume only after the checkpointed user decision is recorded as
  `resume_evidence`; no agent may auto-unblock it.

## Per-Task delivery loop

Work strictly serially: do not start the next Task until the current Task archive is
fully recorded and checkpointed.

1. After human plan approval, record the selected Task as `in_progress` with a
   worker-owned checkpoint.
2. For a non-trivial Task, create one Worker subagent when the host supports
   subagents, using the packet in `references/subagent-handoff.md`. It changes only
   the Task and returns evidence, residual risk, and one recommended next action; it
   never commits, pushes, or edits state/review conclusions. If subagents are not
   available, run the Worker role in an isolated fresh context.
3. After Worker evidence exists, create a fresh read-only Reviewer subagent for every
   round when supported; otherwise use a separate fresh review context. It returns
   PASS or FAIL plus one recommended next action; it never edits files.
4. Write the review artifact first, then record the verdict, evidence, failure count,
   and checkpoint in `state.json`.
5. On the first FAIL, send only bounded findings to the Worker. On the second
   consecutive FAIL, block and ask the user to choose refactor, design correction, or
   Task split. Do not automatically start another repair round.
6. On PASS, rerun self-test and cumulative regression. Notify the user immediately
   before the local code commit; state and review artifacts, not Task documents,
   record runtime progress.
7. Commit only the exact code/test/runtime file list with a unique subject such as
   `GOAL-001 TASK-001: <summary>`. Compare changed files with the recorded manifest,
   then archive the Task and checkpoint the next Task or Goal-level acceptance.
8. On interruption, resume only from the saved checkpoint. If it cannot be verified,
   block and notify the user instead of guessing.

Use host-native runtime labels for Worker and Reviewer contexts, for example
`goal_001_task_002_worker` and `goal_001_task_002_r01_reviewer`; never persist those
names in state.

Never imply push, publish, PR creation, CI, or deployment from a passing review.

## Close the Goal

Before requesting acceptance, evaluate every Goal acceptance criterion and run the
full cumulative regression. Record direct evidence, then set the user-owned
acceptance checkpoint. Report behavior, commits, validation, limitations, rollback
notes, and the exact human decision needed next.

After explicit acceptance, manually record non-empty human acceptance evidence and
move the Goal to `accepted`. This is local metadata, not a documentation commit.
Treat release, merge, push, PR, CI, and deployment as separate approved workflows.

## Conditional references

- Read `references/subagent-handoff.md` before delegating Worker or Reviewer work.
- Read `references/semantic-invariants.md` for data, aggregation, cache, API, or
  migration Tasks; skip it for ordinary UI or isolated configuration work.
- Keep evidence terse: command, exit result, and affected acceptance criteria.
  Detailed findings belong in the canonical review artifact, not duplicated logs.

## Final reporting

Lead with the current gate or outcome. Include Goal/Task status, changed behavior,
validation and review evidence, local commits, residual risks, and the exact required
human decision.
