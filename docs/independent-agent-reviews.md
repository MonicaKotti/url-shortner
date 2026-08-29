# Independent specialist reviews

Three live Codex subagents independently reviewed this prototype before finalization. These were real delegated
review sessions, distinct from the deterministic scenario fixtures under `runs/`.

## Assignment audit

The assignment auditor confirmed the product/control-plane separation and runnable API, then challenged the
quality of the orchestration evidence. Its findings drove machine-enforced exit gates, combined scenario traits,
stronger summaries, Git commit verification, and clearer language distinguishing fixtures from live agent work.

## Workflow forward test

The workflow tester tried a brownfield, materially ambiguous bulk-idempotency requirement. It found that the old
exclusive scenario enum could not route through both clarification and codebase impact, and identified missing
fallback enforcement, exhausted retry budgets after replanning, and incorrect MTTR pairing. The workflow now
supports combined traits, records fallback selection, resets invalidated attempt budgets while retaining history,
and pairs recovery with the failed node.

## Security and privacy review

The security reviewer verified parameterized SQL and the absence of server-side URL fetching, while finding
unenforced gates, persistence of unredacted credentials, an unsafe production analytics salt default, excessive
analytics detail, and unbounded stale rate-limit keys. The implementation now rejects credential-like workflow
content, validates production salt strength, stores only referrer origins and coarse user-agent families, and
removes stale limiter identities.

## Residual limitations

Reviewer identity and roles are asserted by a trusted local operator rather than an organizational identity
provider. The event ledger is hash-chained for tamper detection but remains local storage. Rollback requires and
verifies evidence; it intentionally does not perform destructive Git operations on behalf of an unauthenticated
caller. Production use needs managed identity, immutable storage, retention enforcement, and deployment-system
integration.
