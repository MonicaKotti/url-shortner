# Agentic Software Engineering System - URL Shortener

This repository contains two deliberately separate systems:

1. A deterministic URL-shortener data plane with APIs, analytics, expiration, reliability controls, and tests.
2. A Codex-native, governed SDLC control plane that turns requirements into traceable engineering runs using specialist subagents, an explicit DAG, human gates, bounded retries, rollback controls, audit events, metrics, and dynamic replanning.

No agent or model runs on the redirect request path.

## Quick start

Requires Python 3.11+.

```bash
make install
cp .env.example .env
set -a
source .env
set +a
make run
```

Open:

- Web interface: <http://localhost:8000/>
- API documentation: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Readiness: <http://localhost:8000/ready>
- Prometheus-format application metrics: <http://localhost:8000/metrics>

Production-mode secrets must be changed from the example values. For a containerized run:

```bash
ADMIN_API_KEY='replace-me' ANALYTICS_SALT='replace-with-at-least-32-random-chars' docker compose up --build
```

## Use the web interface

The dependency-free **Signal Desk** interface serves from the application root. Its public workspace creates a
short link with an optional alias and expiration, then offers copy and open actions. The operator workspace lists
links, reveals per-link analytics, and confirms before disabling a link.

In the default local environment, enter `change-me` in Operator access. The key remains only in page memory: it is
never written to browser storage and is cleared on disconnect or page close. Set `ADMIN_API_KEY` to a unique secret
outside local development. A separate frontend server or build command is not required.

## Exercise the API

Create a link:

```bash
curl -i -X POST http://localhost:8000/api/v1/links \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: interview-demo-1' \
  -d '{"url":"https://example.com/articles/42","custom_alias":"article-42"}'
```

Redirect without following it:

```bash
curl -i http://localhost:8000/article-42
```

Inspect analytics:

```bash
curl -H 'X-Admin-Key: change-me' \
  http://localhost:8000/api/v1/links/article-42/analytics
```

Disable a link:

```bash
curl -i -X DELETE -H 'X-Admin-Key: change-me' \
  http://localhost:8000/api/v1/links/article-42
```

## Run validation

```bash
make check
python3 -m pytest --cov=app --cov-report=term-missing
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/agentic-sdlc
```

The committed suite covers domain behavior, API integration, authentication, idempotency, analytics, cache
invalidation, expiration, rate limiting, complete workflow traversal, combined scenario routing, enforced evidence
gates, role-restricted approvals, fan-out/fan-in synchronization, retries, rollback verification, replanning,
hash-chained audit events, metrics, and summaries.

## Run the agentic workflow

Codex loads repository rules from `AGENTS.md`, specialist definitions from `.codex/agents/`, and the reusable workflow from `.agents/skills/agentic-sdlc/SKILL.md`.

Start a ledger manually:

```bash
python3 .agents/skills/agentic-sdlc/scripts/workflow.py start \
  --scenario brownfield \
  --requirement-file path/to/requirement.md
```

The lead Codex agent then delegates ready nodes, records structured results with `transition`, pauses at `approve` gates, and finishes with `metrics` and `summary`. See the skill for the complete procedure.

Use `status --run-id <id>` to discover ready nodes and `handoff --run-id <id> --node <node>` to build a
dependency-scoped specialist handoff. Add `--trait ambiguous` to a brownfield start when both conditions apply.

Regenerate the three example runs only after moving or removing the existing `runs/<scenario>` directories:

```bash
python3 scripts/generate_demo_runs.py
```

The generator refuses to overwrite existing audit evidence.

## Repository map

```text
.codex/agents/                  Specialist Codex agent definitions
.agents/skills/agentic-sdlc/   Reusable governed workflow and ledger utility
workflows/sdlc.yaml             Explicit dependency graph, gates, retries, fallbacks
runs/                           Immutable-style scenario evidence and aggregate metrics
app/                            Deterministic URL-shortener application
app/static/                     Dependency-free Signal Desk web interface
tests/                          Application and orchestration validation
docs/                           Architecture, API contract, scenarios, testing, summary
```

## Documentation

- [Architecture](docs/architecture.md)
- [Scenario evidence](docs/scenarios.md)
- [Testing, risks, and trade-offs](docs/testing-and-tradeoffs.md)
- [Final engineering summary](docs/final-engineering-summary.md)
- [Independent specialist reviews](docs/independent-agent-reviews.md)
- [Static OpenAPI schema](docs/openapi.json)
