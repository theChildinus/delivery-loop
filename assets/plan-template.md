# Delivery plan: <Goal title>

- Goal: GOAL-<NNN>
- Document mode: small | decomposed
- State source: `state.json`
- Dedicated branch:
- Dedicated worktree:
- PRD: `prd.md`
- Design: `design.md`

## Goal

<One user-verifiable delivery outcome>

## Scope and invariants

- In scope:
- Non-goals:
- Compatibility or data invariants:

## Acceptance and stopping condition

- Goal acceptance criteria:
- Human acceptance gate:

## Prior Goal baseline

- Accepted Goals relied on: none | `GOAL-<NNN>`
- Stable behavior that must remain valid:
- Baseline regression command and evidence:

## Task plan

| Task | Feature (optional) | Task goal | Document | Dependencies | Self-test | Cumulative regression | Commit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-001 | None |  | `plan.md` or `tasks/task-001.md` | None |  | Baseline or N/A | `GOAL-001 TASK-001: <summary>` |

## Features (optional)

| Feature | Name | Included Tasks |
| --- | --- | --- |
| FEATURE-001 |  | TASK-001 |

For small mode, keep the single Task's definition below and do not create a
duplicate Task file. For decomposed mode, keep only the Task index here and place
each Task definition in its linked Task document. Runtime status and evidence belong
only in `state.json` and canonical review artifacts.

## Regression strategy

- Stable baseline suite:
- Previously accepted Goal behavior covered by the baseline:
- How each later Task expands or reuses the cumulative scope:
- Goal-level full regression command:

## Small-task definition

Delete this section in decomposed mode.

### Goal and acceptance criteria

- Goal:
- [ ] Acceptance criterion:

### Self-test

```bash
<Focused command>
```


### Cumulative regression plan

- Earlier completed Tasks covered: none; establish baseline

```bash
<Baseline or regression command>
```

### Intended local commit

- Commit message:
- Expected files:
