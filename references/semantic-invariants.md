# Semantic invariants

Load this reference only for data, aggregation, cache, API, or migration Tasks.
Select the applicable checks before implementation; add a focused test for each
selected risk that is not already covered.

- Distinguish absent data, explicit zero, successful `no_data`, partial result, and
  query failure. Never turn a failed lookup into zero.
- Validate numeric domains and relationships: non-negative values, bounded ratios,
  counters, denominators, and `success <= total` style invariants.
- Preserve locality: one malformed labelled record must not corrupt unrelated
  records; unassignable response corruption may fail the batch.
- For staged reads, validate the expected business keys exactly once. Reject missing,
  duplicate, and unexpected rows rather than silently treating them as no data.
- Keep status and payload consistent. A contradictory stored status and payload is
  failure evidence, not a reason to manufacture success.
- Stabilize response shapes: document empty arrays versus `null`, date boundaries,
  optional fields, and typed validation versus internal errors.
- Exercise zero, one, boundary, malformed, and partial-failure paths in addition to
  the happy path.
