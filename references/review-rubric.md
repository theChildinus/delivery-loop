# Task review rubric

Review the selected Task only, but follow affected execution paths far enough to detect regressions.

## Pass conditions

A Task passes only when all are true:

1. Every acceptance criterion maps to code, tests, or direct runtime evidence.
2. The implementation matches the PRD and design semantics, including error and zero-value paths.
3. The diff stays within the Task boundary or documents a necessary exception.
4. Focused tests or equivalent checks exercise the changed behavior.
5. Cumulative regression evidence covers the acceptance criteria of every earlier completed Task, not just the current diff.
6. Persistent state names every earlier Task in `regression_task_ids` and records direct review evidence, not only a verdict string.
7. Every review round has a canonical local artifact that remains outside the code
   archive.
8. A direct Git/archive-manifest comparison proves the exact code manifest matches,
   archive order is sequential, delivery artifacts are excluded in code-only mode,
   and archived code files are currently clean.
9. The Task document records its goal, self-test evidence, regression evidence, review result, and intended commit archive.
10. No unresolved correctness, security, data integrity, concurrency, compatibility, or operability risk blocks delivery.
11. No unrelated user changes are overwritten or bundled accidentally.
12. New Goal artifacts use one Goal-scoped root and lowercase generated paths; no
    artifact overwrites or escapes into an accepted historical Goal directory.
13. The first Task's baseline covers stable behavior from relied-on accepted Goals;
    `regression_task_ids` remains scoped to earlier Tasks in the current Goal.
14. `archive_files` contains no delivery artifacts or files owned by a different
    Goal.

## Review order

Inspect in this order:

1. Correctness and missing behavior.
2. Security, permissions, and data exposure.
3. Data semantics, migrations, compatibility, and rollback.
4. Concurrency, retries, idempotency, and partial failure.
5. Tests and validation integrity.
6. Cumulative regression scope and evidence freshness.
7. Maintainability issues that create a concrete defect risk.

Do not fail a Task for subjective style preferences alone.

## Finding format

For every blocking finding, report:

- severity: `critical`, `high`, `medium`, or `low`;
- precise file and line or symbol;
- violated acceptance criterion or invariant;
- concrete failure scenario;
- smallest defensible correction;
- missing test or verification, when applicable.

End with exactly one verdict: `PASS` or `FAIL`.

Use `PASS` only when no blocking findings remain. List non-blocking residual risks separately without weakening the verdict.
