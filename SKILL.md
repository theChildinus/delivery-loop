---
name: delivery-loop
description: Turn an ambiguous software requirement into a clarified PRD, technical design, Goal/optional Feature/Task plan, and a human-gated Worker-Reviewer delivery loop with persistent state. Use when the user asks to develop a feature from requirements, formalize a product discussion into an executable plan, run task-by-task implementation and review, resume a partially completed delivery Goal, or establish a human-gated delivery workflow. Do not use for a one-line edit, a read-only code review, or an already-scoped standalone fix that does not need product decomposition.
---

# Delivery Loop

Turn a product conversation into a resumable, human-gated delivery system. Keep
product decisions in the main task; delegate only bounded implementation and review.

## Non-negotiables

1. Read applicable `AGENTS.md`, resolve the repository/write scope, and preserve
   unrelated user changes.
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
reuse an accepted Goal root. New Goals use `schema_version: 7`, `state_mode: manual`,
and `archive_mode: code_only`: delivery artifacts stay local and code commits contain
only implementation, tests, and required runtime configuration. Never add
`docs/delivery/**` to a code-only commit or edit `.gitignore` on the user's behalf.

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
acceptance criteria, focused self-test, cumulative regression, intended local commit,
and the dedicated branch or worktree.

For every Task, define both:

- **Self-test:** evidence for this Task's acceptance criteria.
- **Cumulative regression:** evidence that all earlier `done` Tasks still hold. The
  first Task records a stable baseline; use an explicit N/A reason only when no
  prior behavior exists.

Initialize `state.json` with Goal `awaiting_plan_approval` and Tasks `planned` or
`blocked`. Inspect the complete JSON after writing it: it must be valid JSON, its
`goal.state_path` must name the current Goal root, and every `status_history` must
end with that entity's current `status`.

Present scope, tradeoffs, validation strategy, and non-goals. Stop for explicit plan
approval.

## Manual state protocol

`state.json` is the only delivery-state source of truth. Maintain it with a single
intentional edit after the underlying fact exists. Never infer an event from a vague
conversation, and never overwrite evidence or history to make the state convenient.

Goal states are `awaiting_plan_approval`, `in_progress`, `awaiting_acceptance`,
`accepted`, and `blocked`. Task states are `planned`, `ready`, `in_progress`,
`review_failed`, `review_passed`, `blocked`, and `done`.

For every manual transition:

1. Read the current `state.json`, relevant Git history, and review artifact first.
2. Create the review artifact or code commit before recording it in state.
3. Update the entity's `status` and append the same new value to `status_history`.
4. Add only direct evidence to the relevant evidence list; preserve prior entries.
5. Re-read the whole `state.json` and verify its paths, current statuses, histories,
   dependencies, and human gate still agree.

Apply these transitions exactly:

| Event | Required state update |
| --- | --- |
| Initialize | Goal is `awaiting_plan_approval`, `plan_approved: false`; Tasks are `planned` or `blocked` with a non-empty `blocked_reason`. |
| Approve and start a Task | Record the explicit plan approval by setting `plan_approved: true`; append Goal `in_progress`. For a `planned` Task, append `ready`, then `in_progress`, set `base_commit` to the current HEAD, and list every earlier completed Task in `regression_task_ids`. A failed-review Task may move back to `in_progress`. Do not start a Task until all earlier Tasks are `done`. |
| Record review | First create `reviews/<task-id-lower>/round-<nn>.md` with one `PASS` or `FAIL` verdict. Increment `review_round`, append its path to `review_artifacts`, set `review_verdict`, add review/self-test/regression/validation evidence, then append `review_passed` or `review_failed`. |
| Archive a Task | Only after `review_passed`, commit exactly the Task's code/test/runtime files. Record the exact commit subject, full hash, and file manifest in the archive fields, append `done`, and keep delivery artifacts out of `archive_files`. When every Task is `done`, append Goal `awaiting_acceptance`. |
| Accept a Goal | Only from `awaiting_acceptance` and only after explicit human acceptance. Append acceptance evidence and Goal `accepted`; do not create a code commit for this metadata. |
| Block or resume | Set `blocked_reason` before appending `blocked`. Resume only to the state supported by existing evidence; retain the reason as history rather than deleting it. |
| Recover after interruption | Reconcile state with the next review artifact or exactly one matching post-`base_commit` code commit. Record only uniquely supported facts. If proof is missing or ambiguous, block the Task and ask for direction. |

## Per-Task delivery loop

Work strictly serially: do not start the next Task until the current Task archive is
fully recorded.

1. After human plan approval, manually record the selected Task as `in_progress`
   according to the protocol above.
2. For a non-trivial Task, create one Worker. Reuse it only for bounded repair rounds
   of the same Task. Give it the Task, relevant design/PRD, repository instructions,
   permitted scope, tests, and newest FAIL artifact when applicable. It changes only
   the Task, runs self-test and cumulative regression, and never commits, pushes, or
   edits state/review conclusions.
3. After Worker evidence exists, create a fresh read-only Reviewer for every round.
   Give it the acceptance criteria, relevant design, `base_commit`, exact diff, terse
   test evidence, and `references/review-rubric.md`. It returns evidence-backed PASS
   or FAIL only and never edits files.
4. Write the review artifact first, then manually record its round, verdict, and
   evidence in `state.json`.
5. On FAIL, return only the bounded findings to the Worker and repeat. After two
   consecutive FAIL verdicts, or a material/cross-responsibility change, reread the
   full implementation. After two consecutive FAIL verdicts, choose refactor, design
   correction, or Task split, then create a new Worker before continuing.
6. On PASS, rerun self-test and cumulative regression, update the Task document, and
   notify the user immediately before creating its local code commit.
7. Commit only the exact code/test/runtime file list with a unique subject such as
   `GOAL-001 TASK-001: <summary>`. Compare the commit's changed-file list against the
   recorded manifest, then manually archive the Task in `state.json`.
8. On interruption, inspect state, Git, and review artifacts first; apply the manual
   recovery rule rather than guessing.

Name agents as runtime labels, for example `goal_001_task_002_worker` and
`goal_001_task_002_r01_reviewer`; never persist those names in state.

Never imply push, publish, PR creation, CI, or deployment from a passing review.

## Close the Goal

Before the final archive, run Goal-level acceptance checks and full cumulative
regression. The final Task archive moves the Goal to `awaiting_acceptance`. Report
behavior, commits, validation, limitations, rollback notes, and the exact human
decision needed next.

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
