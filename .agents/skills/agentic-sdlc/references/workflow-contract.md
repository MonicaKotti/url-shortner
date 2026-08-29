# Workflow contract

## Agent result

Every agent node must return a JSON-serializable object containing:

- `status`: `completed`, `failed`, or `needs_input`
- `summary`: concise observable result
- `artifacts`: repository-relative artifact paths
- `evidence`: commands, test results, file references, or hashes
- `decisions`: decisions made within the agent's approved scope
- `risks`: newly identified or residual risks
- `assumptions`: assumptions that affected the result
- `git_commit`: implementation commit when the node changed code

Do not include hidden reasoning or chain-of-thought.

## State model

Node states are `pending`, `ready`, `running`, `waiting_approval`, `completed`, `failed`, `invalidated`, `rolled_back`, or `skipped`.

A run is `running`, `waiting_approval`, `completed`, `failed`, `safe_stopped`, or `rolled_back`.

Only completed dependencies satisfy a node. A conditional dependency that does not apply must be marked `skipped` before its dependent can become ready.

## Gate rules

- Entry gates validate that required upstream inputs exist.
- Exit gates validate structured evidence, not agent confidence.
- Human gates record actor, decision, timestamp, comment, and the artifact hashes being approved.
- Rejection triggers safe stop unless an approved fallback route exists.

## Retry rules

- Retry only a classified transient failure.
- Increment attempts before execution.
- Never exceed `max_attempts`.
- Preserve errors from every attempt in `events.jsonl`.
- Exhaustion triggers the node's fallback or safe stop.

## Replanning rules

Hash each node's effective inputs. When an upstream output changes, find every descendant, preserve its old output as superseded, and set it to `invalidated`. Re-run only the affected subgraph after required approvals are renewed.

## Recovery rules

- Code changes: discard the isolated branch/worktree or revert a known commit.
- Database changes: use an approved down or compensating migration.
- Deployment: redeploy a known-good immutable manifest.
- Irreversible external effects: stop and escalate; never claim rollback.

## Metrics

Calculate total runs, terminal success rate, node attempts, retry frequency, rollback frequency, safe-stop frequency, mean end-to-end latency, and MTTR from first failure to recorded recovery. Report unavailable metrics as unavailable rather than zero.
