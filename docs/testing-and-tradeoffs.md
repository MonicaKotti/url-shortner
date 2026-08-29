# Testing, risks, and trade-offs

## Testing approach

- **Domain tests:** expiration boundaries and gone-link behavior.
- **API integration tests:** create, redirect, analytics, idempotency, aliases, URL policy, admin authorization, disablement, operational endpoints, security headers, and rate limiting.
- **UI integration tests:** application-shell and asset delivery, restrictive UI-only browser headers, static-route
  precedence over the redirect catch-all, preservation of redirects, and source checks against persistent credential
  storage and unsafe HTML insertion.
- **Workflow tests:** complete traversal, combined conditional routing, enforced evidence gates, fan-out/fan-in
  readiness, authorized human approvals, transient retry, node-specific MTTR, downstream invalidation, rejected-gate
  safe stop, verified rollback recording, aggregate metrics, and summary generation.
- **Static checks:** Ruff linting and formatting for application, tests, demo generator, and deterministic workflow script.
- **Skill validation:** the official skill-package validator checks naming and frontmatter.
- **Container check:** Docker health check exercises the service health endpoint.

## Security and privacy controls

- HTTP/HTTPS scheme allowlist and rejection of embedded credentials.
- Parameterized database operations.
- Cryptographically random default codes and constrained custom aliases.
- Admin API-key boundary for metadata, analytics, listing, and disablement.
- Constant-time API-key comparison.
- Salted, truncated client-IP hashes instead of raw IP storage.
- Per-process sliding-window abuse limit.
- Bounded headers and analytics strings.
- Production startup rejects example secrets.
- No agents or LLM calls in request handling.
- UI-only restrictive CSP, permissions policy, same-origin opener isolation, protocol-safe generated links, and
  `textContent` rendering for server-derived values.
- Operator credentials live in memory only and are cleared on disconnect or page close.

## Failure scenarios

| Failure | Current behavior | Production evolution |
|---|---|---|
| Code collision | Retry up to five generated codes | Same policy with collision telemetry |
| Duplicate create retry | Idempotency key returns the original resource | Shared idempotency store |
| Expired/disabled link | HTTP 410; no click recorded | Same |
| Database unavailable | Readiness fails; request surfaces server error | Circuit breaker, replicas, alerts |
| Process restart | SQLite persists; cache warms lazily | Distributed cache or database-first reads |
| Agent transient failure | Bounded retry and recovery metric | Same with durable job leases |
| Agent permanent failure | Safe stop and preserved branch/evidence | Operator remediation queue |
| Rejected high-risk decision | Safe stop; no merge/deploy | Same |
| Upstream output changes | Descendants invalidated and rerun | Same with database-backed ledger |

## Trade-offs and limitations

- **SQLite:** appropriate for a local, single-node prototype, but write concurrency and horizontal scale require PostgreSQL or a comparable managed datastore.
- **In-process cache:** intentionally demonstrates the ambiguous performance scenario. Multi-instance deployment requires shared invalidation or a very short TTL; a stale instance could otherwise redirect a recently disabled link until expiry.
- **Synchronous analytics write:** simple and strongly observable, but adds redirect latency. Production scale should enqueue click events and tolerate at-least-once delivery with idempotent aggregation.
- **In-process rate limiting:** protects one instance only. Use Redis or an edge gateway for distributed enforcement.
- **API-key administration:** sufficient for a prototype. Production should use identity-aware authentication, scoped authorization, rotation, and audit integration.
- **Browser operator workspace:** convenient for a local demonstration, but a bearer-style admin key in page memory
  is not a substitute for authenticated sessions, CSRF protection, role-scoped authorization, and server-side audit.
- **No frontend build step:** reduces dependencies and deployment complexity, but browser behavior is validated with
  integration and source-policy tests rather than a full end-to-end browser automation suite.
- **File-backed workflow state:** atomic and locked on one machine, not a distributed workflow database. Production should use durable leases and transactional state storage.
- **Native Codex dependency:** custom agent syntax is Codex-specific. The workflow contract and DAG are portable, while Claude Code would need corresponding Markdown agent definitions.
- **Demo timings:** deterministic scenario outputs produce millisecond timings and should not be treated as capacity measurements.
- **No deployment:** release approval in the evidence authorizes a candidate only; it does not claim a production deployment occurred.
