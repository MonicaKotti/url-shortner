---
name: agentic-sdlc
description: Execute governed software-engineering work from a requirement through design, implementation, validation, documentation, and release readiness. Use for feature, brownfield, refactor, bug-fix, or ambiguous-requirement tasks that require explicit dependencies, specialist subagents, human gates, retries, rollback, audit evidence, metrics, or dynamic replanning.
---

# Governed Agentic SDLC

Treat the lead Codex thread as the orchestrator. Use native subagents as bounded specialists and the repository's Git history as the change-recovery boundary.

## Start a run

1. Read `AGENTS.md`, `workflows/sdlc.yaml`, and [the workflow contract](references/workflow-contract.md).
2. Require a clean or understood worktree. Never overwrite unrelated user changes.
3. Create an isolated Git branch or worktree for code-writing nodes.
4. Run `scripts/workflow.py start --scenario <greenfield|brownfield|ambiguous> --requirement-file <path>`.
   Add repeatable `--trait brownfield|ambiguous` flags when conditions overlap.
5. Preserve the emitted run identifier for every subsequent event.

## Execute the graph

1. Use `scripts/workflow.py status --run-id <id>` to select ready nodes.
2. Spawn the configured specialist agent for each selected node. Parallelize independent read-heavy nodes; keep one implementation owner.
3. Build the scoped input with `scripts/workflow.py handoff --run-id <id> --node <node>` and give the agent only
   that approved upstream context, its task scope, its tool boundary, and the required output contract.
4. Record completion with `scripts/workflow.py transition`. Include observable evidence and artifact paths; never record chain-of-thought.
5. Treat missing or failed exit-gate evidence as failure.
6. Retry only transient failures, at most `max_attempts`. Record every attempt.
7. Stop at `approval: required`. Continue only after `scripts/workflow.py approve` records an authorized role,
   actor, decision, and upstream hashes.

## Replan and recover

- When an upstream requirement or decision changes, run `scripts/workflow.py replan`. Invalidate all affected descendants and preserve superseded outputs for lineage.
- On exhausted retries, rejected approval, policy violation, or an unsafe state, run `scripts/workflow.py safe-stop`.
- Prefer discarding an unmerged isolated worktree. Revert commits only when discarding is not possible. Record a
  rollback only after providing verification evidence and a valid Git ref when applicable.
- Never claim that an email, external action, or irreversible migration was rolled back merely because code was reverted.

## Finish a run

1. Require successful test, security, documentation, and release-review nodes.
2. Require explicit human release approval before merge or deployment.
3. Run `scripts/workflow.py metrics` and `scripts/workflow.py summary`.
4. Verify the summary covers rationale, artifacts, risks, trade-offs, validation, assumptions, limitations, approvals, rollback readiness, and unresolved items.

## Output rules

- Store run state below `runs/<run-id>/`.
- Use Git commit hashes and diffs for code lineage; do not duplicate source files into JSON.
- Store structured agent outputs below `runs/<run-id>/nodes/`.
- Keep `events.jsonl` append-only; the hash chain detects modification of retained events.
- Redact secrets, credentials, personal data, and model chain-of-thought.
