# Agentic URL Shortener Working Agreement

## Mission

Turn engineering requirements into reviewable, validated changes to the deterministic URL-shortener service. Use the `agentic-sdlc` skill for feature, brownfield, refactor, bug-fix, or ambiguous-requirement work.

## Autonomy boundaries

- Keep agent work on an isolated Git branch or worktree until the release gate is approved.
- Require human approval before schema-destructive operations, dependency changes with material operational impact, release, or merge to the baseline branch.
- Never place an LLM or agent on the URL redirect request path.
- Do not record chain-of-thought. Record observable inputs, decisions, outputs, commands, artifacts, and validation evidence.
- Retry only transient failures and never exceed the workflow node's configured retry limit.
- On exhausted retries or rejected high-impact gates, stop safely and preserve all evidence.

## Delegation

- Delegate requirement normalization to `requirements_analyst`.
- Delegate brownfield impact analysis to `codebase_explorer` before design.
- Delegate architecture to `architect` after requirements are accepted.
- Use a single `implementer` as the owner of code changes.
- Run `test_reviewer`, `security_reviewer`, and `documentation_reviewer` independently after implementation when their dependencies permit.
- Delegate release evidence review to `release_reviewer`; only a human may approve release.

## Quality gates

- Run formatting, static checks, unit tests, and API integration tests after application changes.
- Require concrete evidence for every completed node.
- Treat missing evidence as a failed exit gate.
- Update public API documentation when behavior changes.
- Document assumptions, residual risks, limitations, and rollback strategy.

## Code conventions

- Use Python 3.11+ and type hints.
- Keep transport, domain, persistence, and orchestration concerns separated.
- Use UTC ISO-8601 timestamps.
- Preserve privacy by storing only salted hashes for client IP analytics.

