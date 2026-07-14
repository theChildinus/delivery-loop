# State compatibility

Read this reference only when resuming a historical v5 Goal or migrating v1-v5 state.
New Goals use schema v6 and must not load this file by default.

## Version policy

- Schema v6 uses `archive_mode: code_only`: delivery documents remain local and
  each `done` Task records a code commit hash and code-only file manifest.
- Schema v5 is the historical audited format: Task and Goal archive commits include
  their canonical state and delivery artifacts. Retain this behavior when resuming v5.
- Do not change required fields or archive rules within an existing schema version.
- Do not auto-migrate an active Goal. The validator supports both v5 and v6.

## Explicit migration

Use the migration script only for v1-v4 state or a v5 state without `layout`:

```bash
python3 <skill-dir>/scripts/migrate_delivery_state.py \
  <goal-root>/state.json <goal-root>/state.v5.json
```

It never overwrites input. Inspect its result and replace the original deliberately.
The migration preserves evidence and records provenance; unverifiable legacy entities
become `blocked` with `legacy_gaps` rather than receiving placeholder evidence.

For a pre-layout v5 fixed directory, the upgrader records only already-existing
uppercase Task/review paths as legacy exemptions. Every later path must be lowercase.
Do not copy historical Tasks into a new Goal: record relied-on accepted Goals in the
new plan and cover them through the stable baseline regression suite.
