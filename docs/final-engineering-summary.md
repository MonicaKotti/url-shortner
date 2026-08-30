# Final engineering summary

## Plan and rationale

The implementation separates deterministic product behavior from agentic engineering control. FastAPI and SQLite make the URL service runnable locally with minimal setup, while interfaces and documented migration paths preserve a production evolution. Codex-native agent definitions demonstrate real specialist delegation without pretending agents belong in redirect processing.

The orchestration layer combines declarative configuration with deterministic enforcement: Markdown/TOML defines agent behavior, YAML defines the graph, the Codex runtime performs reasoning and delegation, the ledger utility enforces state and evidence rules, and Git owns code lineage and recovery.

## Artifacts

- Runnable URL-shortener application and container definition
- Responsive Signal Desk web interface for public shortening and operator analytics
- Versioned REST API and static OpenAPI schema
- Unit and API integration tests
- Eight specialist Codex agent definitions
- Reusable governed SDLC skill
- Explicit conditional dependency graph
- Deterministic state, audit, approval, retry, rollback, replan, metrics, and summary utility
- Greenfield, brownfield, and ambiguous scenario ledgers
- Independent live assignment, workflow, and security specialist reviews
- Architecture, setup, testing, security, risk, trade-off, and limitation documentation

## Validation

- Ruff passes for all executable Python sources.
- The complete 22-test suite passes with application coverage reported separately by the command in `README.md`.
- The skill-package validator passes.
- Three scenario state files finish in `completed` status.
- Scenario ledgers compare the pre-application governance baseline `c674e01` with implementation commit `7f31ecf`;
  they are retrospective reproducible evidence, not a claim that the fixture generator authored those commits.
- Brownfield evidence contains one retry and a measured recovery interval.
- Ambiguous evidence contains one replan and retained superseded architecture output.
- Aggregate metrics report all three terminal runs.

## Risks and trade-offs

The local persistence, cache, rate limiter, and workflow ledger are single-node components. They are intentionally explicit and testable, but not substitutes for PostgreSQL, shared caching/invalidation, edge abuse protection, event streaming, or a durable distributed workflow store at scale. The native agent definitions also require equivalent adapters for non-Codex runtimes.

## Assumptions

- The interview prototype runs locally as one application instance.
- Human approval records in committed demo runs are clearly labeled `interview-demo-reviewer` and are demonstration evidence, not production authorization.
- Git branches/worktrees are available for implementation isolation.
- Redirect targets are not fetched by the service, so the URL policy addresses open-redirect abuse rather than SSRF from server-side retrieval.

## Limitations

- The Signal Desk consumer/operator UI is included; Swagger UI and run artifacts remain the API and workflow
  review interfaces.
- No production deployment, email, ticket, or other external side effect is performed.
- Demo agent outputs are deterministic fixtures exercising the state machine. Actual delegated review evidence is
  summarized in `docs/independent-agent-reviews.md`; the fixtures are not presented as agent-authorship proof.
- Rollback of irreversible external effects cannot be guaranteed and is deliberately escalated.

## Release readiness

The repository is locally runnable, tested, documented, recoverable through Git, and contains evidence for the required scenarios and governance controls. Before a real production release, migrate state to managed infrastructure, replace prototype authentication and distributed-control components, perform load testing, and integrate organizational identity, observability, and change-management systems.
