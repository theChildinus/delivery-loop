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
reuse an accepted Goal root. New Goals use schema v6 and `archive_mode: code_only`:
delivery artifacts stay local and code commits contain only implementation, tests,
and required runtime configuration. Never add `docs/delivery/**` to a code-only
commit or edit `.gitignore` on the user's behalf.

Before creating a Goal, enumerate `docs/delivery/state.json` and
`docs/delivery/*/state.json`; choose an ID and root that do not collide with any
existing Goal, including a blocked or unaccepted one.

Schema v5 is the historical audited format. When resuming or migrating v5, read
`references/state-compatibility.md` and retain its audited archive rules. Do not
change v5 semantics or migrate automatically.

Copy the relevant assets: `prd-template.md`, `design-template.md`, `plan-template.md`,
`task-template.md`, `state-template.json`, and `review-template.md`.

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
commit.

For every Task, define both:

- **Self-test:** evidence for this Task's acceptance criteria.
- **Cumulative regression:** evidence that all earlier `done` Tasks still hold. The
  first Task records a stable baseline; use an explicit N/A reason only when no
  prior behavior exists.

Initialize `state.json` with Goal `awaiting_plan_approval` and Tasks `planned` or
`blocked`, then validate it:

```bash
python3 <skill-dir>/scripts/validate_delivery_state.py \
  docs/delivery/<goal-id-lower>-<slug>/state.json
```

Present scope, tradeoffs, validation strategy, and non-goals. Stop for explicit plan
approval.

## Per-Task delivery loop

Work strictly serially: do not start the next Task until the current Task archive
validates.

1. Start or resume the selected Task with `delivery_state.py start-task`. The first
   Task uses `--approve-plan` after human approval; the script records `base_commit`,
   `ready`, and `in_progress` atomically.
2. For a non-trivial Task, create one Worker. Reuse it only for bounded repair rounds
   of the same Task. Give it the Task, relevant design/PRD, repository instructions,
   permitted scope, tests, and newest FAIL artifact when applicable. It changes only
   the Task, runs self-test and cumulative regression, and never commits, pushes, or
   edits state/review conclusions.
3. After Worker evidence exists, create a fresh read-only Reviewer for every round.
   Give it the acceptance criteria, relevant design, `base_commit`, exact diff, terse
   test evidence, and `references/review-rubric.md`. It returns evidence-backed PASS
   or FAIL only and never edits files.
4. Write the review artifact first. Then use `delivery_state.py record-review` to
   atomically record round, verdict, artifact, and evidence. Do not increment
   `review_round` before an artifact exists.
5. On FAIL, return only the bounded findings to the Worker and repeat. After two
   consecutive FAIL verdicts, or a material/cross-responsibility change, reread the
   full implementation. After two consecutive FAIL verdicts, choose refactor, design
   correction, or Task split, then create a new Worker before continuing.
6. On PASS, rerun self-test and cumulative regression, update the Task document, and
   notify the user immediately before creating its local code commit.
7. Commit only the exact code/test/runtime file list with a unique subject such as
   `GOAL-001 TASK-001: <summary>`. Then use `delivery_state.py archive-task` to record
   its message, hash, and manifest; run `validate_delivery_state.py --check-git`.
8. On interruption, inspect state and Git first. `delivery_state.py recover` records
   an existing next review artifact or one unique matching code commit; it must reject
   zero or multiple candidates rather than guess.

Name agents as runtime labels, for example `goal_001_task_002_worker` and
`goal_001_task_002_r01_reviewer`; never persist those names in state.

Never imply push, publish, PR creation, CI, or deployment from a passing review.

## Close the Goal

Before the final archive, run Goal-level acceptance checks and full cumulative
regression. The final Task archive moves the Goal to `awaiting_acceptance`. Report
behavior, commits, validation, limitations, rollback notes, and the exact human
decision needed next.

After explicit acceptance, run `delivery_state.py accept-goal` with non-empty human
acceptance evidence. In v6 this is local metadata, not a documentation commit. Treat
release, merge, push, PR, CI, and deployment as separate approved workflows.

## Conditional references

- Read `references/state-compatibility.md` only for v1-v5 migration or historical
  v5 resume.
- Read `references/subagent-handoff.md` before delegating Worker or Reviewer work.
- Read `references/semantic-invariants.md` for data, aggregation, cache, API, or
  migration Tasks; skip it for ordinary UI or isolated configuration work.
- Keep evidence terse: command, exit result, and affected acceptance criteria.
  Detailed findings belong in the canonical review artifact, not duplicated logs.

## Final reporting

Lead with the current gate or outcome. Include Goal/Task status, changed behavior,
validation and review evidence, local commits, residual risks, and the exact required
human decision.
