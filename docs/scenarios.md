# Required scenario evidence

The repository includes three completed, reproducible workflow ledgers. These are observable demonstrations generated through the same state machine tested by the suite; they are not transcripts of private model reasoning.

## 1. Greenfield - core service

Requirement: build a secure URL shortener with create, redirect, analytics, health, and API documentation.

Evidence: `runs/greenfield-core-service/`

- Conditional clarification and brownfield-impact nodes were skipped.
- Requirements and architecture completed sequentially.
- Human design approval preceded implementation.
- Test, security, and documentation review synchronized at release review.
- Human release approval preceded the final summary.
- Outcome: completed with no retry, rollback, or replan.

## 2. Brownfield - expiration and disablement

Requirement: add optional expiration and administrative disablement without breaking existing links.

Evidence: `runs/brownfield-expiration/`

- Codebase impact traced schema, create, redirect, cache, analytics, and tests.
- Nullable UTC expiration preserved legacy links.
- Disablement invalidated the local cache and produced HTTP 410 on subsequent redirects.
- The first test-review attempt recorded a transient runner failure.
- The workflow scheduled exactly one bounded retry; the second attempt completed.
- MTTR was calculated from the first failure to the successful recovery event.
- Outcome: completed after one retry.

## 3. Ambiguous - popular links

Initial requirement: “Make popular links faster.”

Evidence: `runs/ambiguous-popular-links/`

- Requirements identified undefined popularity, scale, latency, and freshness.
- A human clarification gate defined repeated reads, a local p95 target, and immediate disable propagation.
- The first cache design completed.
- A changed upstream clarification added immediate invalidation, dynamically invalidating architecture and every affected descendant.
- Architecture reran with explicit local invalidation before design approval.
- Outcome: completed after one governed replan.

## Aggregate reliability evidence

`runs/aggregate-metrics.json` reports:

- Terminal success rate across the three committed scenarios
- Total retries and per-run retry frequency
- Rollback and safe-stop counts
- Replan count
- Mean end-to-end latency
- Mean recovery time when recovery events exist

Very small latencies are expected because the committed demonstrations use deterministic structured agent outputs. Real model/tool latency would be measured by the same event timestamps.
