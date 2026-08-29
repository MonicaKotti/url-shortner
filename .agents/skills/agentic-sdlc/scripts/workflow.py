#!/usr/bin/env python3
"""Deterministic state, audit, gate, replan, and metrics helper for the SDLC skill."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNS_ROOT = REPO_ROOT / "runs"
GRAPH_PATH = REPO_ROOT / "workflows" / "sdlc.yaml"
RESULT_KEYS = {"status", "summary", "artifacts", "evidence", "decisions", "risks", "assumptions"}
TERMINAL_RUN_STATES = {"completed", "failed", "safe_stopped", "rolled_back"}
SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class WorkflowError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temp_path = Path(stream.name)
    os.replace(temp_path, path)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def git_ref() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def git_value(*arguments: str) -> str | None:
    result = subprocess.run(["git", *arguments], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def reject_secrets(value: Any, label: str) -> None:
    serialized = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
        raise WorkflowError(f"{label} appears to contain a credential; redact it before persistence")


def graph() -> dict[str, Any]:
    with GRAPH_PATH.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), dict):
        raise WorkflowError("Invalid workflow graph")
    nodes = value["nodes"]
    for node_id, node in nodes.items():
        dependencies = node.get("depends_on")
        if not isinstance(dependencies, list):
            raise WorkflowError(f"Node {node_id} must declare depends_on")
        unknown = set(dependencies) - set(nodes)
        if unknown:
            raise WorkflowError(f"Node {node_id} has unknown dependencies: {sorted(unknown)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise WorkflowError(f"Dependency cycle detected at {node_id}")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in nodes[node_id]["depends_on"]:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in nodes:
        visit(node_id)
    return value


def run_dir(run_id: str) -> Path:
    if not run_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id
    ):
        raise WorkflowError("Run identifier contains unsafe characters")
    return RUNS_ROOT / run_id


@contextmanager
def locked_run(run_id: str) -> Iterator[tuple[Path, dict[str, Any]]]:
    directory = run_dir(run_id)
    state_path = directory / "state.json"
    if not state_path.exists():
        raise WorkflowError(f"Unknown run: {run_id}")
    with (directory / ".lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_json(state_path)
        try:
            yield directory, state
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def event(directory: Path, event_type: str, actor: str, details: dict[str, Any]) -> None:
    previous_hash = None
    event_path = directory / "events.jsonl"
    if event_path.exists():
        lines = event_path.read_text(encoding="utf-8").splitlines()
        if lines:
            previous_hash = json.loads(lines[-1]).get("event_hash")
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": now(),
        "event": event_type,
        "actor": actor,
        "details": details,
        "previous_hash": previous_hash,
    }
    record["event_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def condition_applies(condition: str | None, traits: set[str]) -> bool:
    if condition is None:
        return True
    return {
        "material_ambiguity_present": "ambiguous" in traits,
        "brownfield": "brownfield" in traits,
    }.get(condition, False)


def dependencies_satisfied(state: dict[str, Any], node: dict[str, Any]) -> bool:
    return all(state["nodes"][dependency]["status"] in {"completed", "skipped"} for dependency in node["depends_on"])


def refresh(state: dict[str, Any]) -> None:
    if state["status"] in TERMINAL_RUN_STATES:
        return
    waiting = False
    for node in state["nodes"].values():
        if node["status"] in {"pending", "invalidated"} and dependencies_satisfied(state, node):
            if node.get("approval") == "required":
                node["status"] = "waiting_approval"
                waiting = True
            else:
                node["status"] = "ready"
        elif node["status"] == "waiting_approval":
            waiting = True
    if all(node["status"] in {"completed", "skipped"} for node in state["nodes"].values()):
        state["status"] = "completed"
        state["completed_at"] = now()
    elif waiting:
        state["status"] = "waiting_approval"
    else:
        state["status"] = "running"
    state["updated_at"] = now()


def cmd_start(args: argparse.Namespace) -> None:
    requirement_path = Path(args.requirement_file)
    requirement = requirement_path.read_text(encoding="utf-8").strip()
    if len(requirement) < 10:
        raise WorkflowError("Requirement must contain at least 10 characters")
    reject_secrets(requirement, "Requirement")
    definition = graph()
    baseline_ref = getattr(args, "baseline_ref", None)
    if baseline_ref:
        baseline_ref = git_value("rev-parse", baseline_ref)
        if not baseline_ref or git_value("cat-file", "-t", baseline_ref) != "commit":
            raise WorkflowError("Baseline ref is not a valid Git commit")
    run_id = args.run_id or f"{args.scenario}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    directory = run_dir(run_id)
    if directory.exists():
        raise WorkflowError(f"Run already exists: {run_id}")
    directory.mkdir(parents=True)
    (directory / "nodes").mkdir()
    started = now()
    nodes: dict[str, Any] = {}
    traits = set(args.trait or ()) | {args.scenario}
    for node_id, node_definition in definition["nodes"].items():
        applicable = condition_applies(node_definition.get("condition"), traits)
        nodes[node_id] = {
            **node_definition,
            "id": node_id,
            "status": "pending" if applicable else "skipped",
            "attempts": 0,
            "execution_count": 0,
            "output_hash": None,
            "last_error": None,
        }
    state = {
        "run_id": run_id,
        "scenario": args.scenario,
        "traits": sorted(traits),
        "requirement": requirement,
        "requirement_hash": hashlib.sha256(requirement.encode()).hexdigest(),
        "status": "running",
        "graph_name": definition["name"],
        "graph_version": definition["version"],
        "replan_count": 0,
        "git_ref_at_start": baseline_ref or git_ref(),
        "git_branch_at_start": git_value("branch", "--show-current"),
        "worktree_at_start": str(REPO_ROOT),
        "started_at": started,
        "updated_at": started,
        "completed_at": None,
        "safe_stop_reason": None,
        "nodes": nodes,
    }
    refresh(state)
    atomic_json(directory / "state.json", state)
    event(
        directory,
        "run.started",
        "orchestrator",
        {
            "scenario": args.scenario,
            "traits": sorted(traits),
            "requirement_hash": state["requirement_hash"],
            "git_ref": state["git_ref_at_start"],
        },
    )
    print(run_id)


def validate_result(path: Path) -> dict[str, Any]:
    result = read_json(path)
    missing = RESULT_KEYS - set(result)
    if missing:
        raise WorkflowError(f"Agent result is missing fields: {', '.join(sorted(missing))}")
    if result["status"] not in {"completed", "failed", "needs_input"}:
        raise WorkflowError("Invalid agent result status")
    reject_secrets(result, "Agent result")
    for field in ("artifacts", "evidence", "decisions", "risks", "assumptions"):
        if not isinstance(result[field], list) or not all(isinstance(item, str) for item in result[field]):
            raise WorkflowError(f"Agent result field {field} must be a list of strings")
    if not isinstance(result["summary"], str) or not result["summary"].strip():
        raise WorkflowError("Agent result summary must be non-empty")
    return result


def validate_exit_gate(node_id: str, node: dict[str, Any], result: dict[str, Any]) -> None:
    if result["status"] != "completed":
        return
    if not result["evidence"]:
        raise WorkflowError(f"Exit gate {node['exit_gate']} requires concrete evidence")
    artifact_required = node_id not in {"intake", "test_review", "security_review", "release_review"}
    if artifact_required and not result["artifacts"]:
        raise WorkflowError(f"Exit gate {node['exit_gate']} requires at least one artifact")
    for artifact in result["artifacts"]:
        candidate = (REPO_ROOT / artifact).resolve()
        if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
            raise WorkflowError(f"Artifact escapes repository: {artifact}")
        if not candidate.exists():
            raise WorkflowError(f"Artifact does not exist: {artifact}")
    if node_id in {"requirements", "architecture"} and not result["decisions"]:
        raise WorkflowError(f"Exit gate {node['exit_gate']} requires recorded decisions")
    if node_id == "implementation":
        commit = result.get("git_commit")
        if not commit or git_value("cat-file", "-t", commit) != "commit":
            raise WorkflowError("Implementation gate requires a valid Git commit")
    if node_id == "security_review" and any(risk.upper().startswith("HIGH") for risk in result["risks"]):
        raise WorkflowError("Security gate rejects unaccepted HIGH-severity findings")


def cmd_transition(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        if state["status"] in TERMINAL_RUN_STATES:
            raise WorkflowError(f"Run is terminal: {state['status']}")
        if args.node not in state["nodes"]:
            raise WorkflowError(f"Unknown node: {args.node}")
        node = state["nodes"][args.node]
        if args.status == "running":
            if node["status"] not in {"ready", "failed", "invalidated"}:
                raise WorkflowError(f"Node cannot start from {node['status']}")
            if node["attempts"] >= node["max_attempts"]:
                raise WorkflowError("Retry budget exhausted")
            node["attempts"] += 1
            node["execution_count"] += 1
            effective_inputs = {
                "requirement_hash": state["requirement_hash"],
                "dependencies": {
                    dependency: state["nodes"][dependency]["output_hash"] for dependency in node["depends_on"]
                },
            }
            node["input_hash"] = hashlib.sha256(json.dumps(effective_inputs, sort_keys=True).encode()).hexdigest()
            node["status"] = "running"
            event(
                directory,
                "node.started",
                args.actor,
                {
                    "node": args.node,
                    "attempt": node["execution_count"],
                    "budget_attempt": node["attempts"],
                    "input_hash": node["input_hash"],
                },
            )
        else:
            if node["status"] != "running":
                raise WorkflowError(f"Node cannot finish from {node['status']}")
            if not args.result:
                raise WorkflowError("A structured --result file is required")
            result = validate_result(Path(args.result))
            if result["status"] != args.status:
                raise WorkflowError("Command status and result status differ")
            validate_exit_gate(args.node, node, result)
            destination = directory / "nodes" / f"{args.node}-attempt-{node['execution_count']}.json"
            atomic_json(destination, result)
            output_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
            node["output_hash"] = output_hash
            if args.status == "completed":
                node["status"] = "completed"
                node["last_error"] = None
                event(
                    directory,
                    "node.completed",
                    args.actor,
                    {
                        "node": args.node,
                        "attempt": node["execution_count"],
                        "output": display_path(destination),
                        "output_hash": output_hash,
                    },
                )
            elif args.status == "needs_input":
                node["status"] = "waiting_approval"
                node["last_error"] = result["summary"]
                state["status"] = "waiting_approval"
                event(directory, "node.needs_input", args.actor, {"node": args.node, "summary": result["summary"]})
            else:
                node["status"] = "failed"
                node["last_error"] = result["summary"]
                event(
                    directory,
                    "node.failed",
                    args.actor,
                    {
                        "node": args.node,
                        "attempt": node["execution_count"],
                        "transient": args.transient,
                        "summary": result["summary"],
                    },
                )
                if args.transient and node["attempts"] < node["max_attempts"]:
                    node["status"] = "ready"
                    event(
                        directory,
                        "node.retry_scheduled",
                        "orchestrator",
                        {"node": args.node, "next_attempt": node["attempts"] + 1},
                    )
                else:
                    fallback = node.get("fallback", "safe_stop")
                    event(directory, "fallback.selected", "orchestrator", {"node": args.node, "fallback": fallback})
                    state["status"] = "safe_stopped"
                    state["safe_stop_reason"] = f"{args.node}: {result['summary']}"
                    state["completed_at"] = now()
                    event(directory, "run.safe_stopped", "orchestrator", {"reason": state["safe_stop_reason"]})
        refresh(state)
        atomic_json(directory / "state.json", state)
        print(
            json.dumps(
                {"run_id": args.run_id, "node": args.node, "status": node["status"], "run_status": state["status"]}
            )
        )


def cmd_approve(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        node = state["nodes"].get(args.node)
        if not node or node["status"] != "waiting_approval":
            raise WorkflowError("Node is not waiting for approval")
        if node.get("approval") != "required":
            raise WorkflowError("Only declared human approval gates can be approved")
        authorized = set(node.get("authorized_roles", []))
        if args.role not in authorized:
            raise WorkflowError(f"Role {args.role} is not authorized for {args.node}")
        record = {
            "node": args.node,
            "decision": args.decision,
            "actor": args.actor,
            "role": args.role,
            "comment": args.comment,
            "timestamp": now(),
            "upstream_hashes": {
                dependency: state["nodes"][dependency]["output_hash"] for dependency in node["depends_on"]
            },
        }
        event(directory, f"gate.{args.decision}", args.actor, record)
        node["attempts"] += 1
        node["execution_count"] += 1
        if args.decision == "approved":
            node["status"] = "completed"
            node["output_hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        else:
            node["status"] = "failed"
            state["status"] = "safe_stopped"
            state["safe_stop_reason"] = f"{args.node} rejected by {args.actor}"
            state["completed_at"] = now()
            event(directory, "run.safe_stopped", "orchestrator", {"reason": state["safe_stop_reason"]})
        refresh(state)
        atomic_json(directory / "state.json", state)
        print(
            json.dumps(
                {"run_id": args.run_id, "node": args.node, "status": node["status"], "run_status": state["status"]}
            )
        )


def descendants(state: dict[str, Any], source: str) -> set[str]:
    found: set[str] = set()
    frontier = [source]
    while frontier:
        current = frontier.pop()
        for node_id, node in state["nodes"].items():
            if current in node["depends_on"] and node_id not in found:
                found.add(node_id)
                frontier.append(node_id)
    return found


def cmd_replan(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        if args.changed_node not in state["nodes"]:
            raise WorkflowError(f"Unknown node: {args.changed_node}")
        affected = descendants(state, args.changed_node)
        if not affected:
            raise WorkflowError("Changed node has no downstream nodes")
        source = state["nodes"][args.changed_node]
        old_output_hash = source["output_hash"]
        if args.new_output_hash:
            source["output_hash"] = args.new_output_hash
        for node_id in affected:
            node = state["nodes"][node_id]
            if node["status"] != "skipped":
                node["status"] = "invalidated"
                node["output_hash"] = None
                node["last_error"] = None
                node.setdefault("superseded_attempts", []).append(node["attempts"])
                node["attempts"] = 0
        state["replan_count"] += 1
        state["status"] = "running"
        state["completed_at"] = None
        event(
            directory,
            "run.replanned",
            args.actor,
            {
                "changed_node": args.changed_node,
                "reason": args.reason,
                "old_output_hash": old_output_hash,
                "new_output_hash": source["output_hash"],
                "invalidated": sorted(affected),
                "replan_count": state["replan_count"],
            },
        )
        refresh(state)
        atomic_json(directory / "state.json", state)
        print(json.dumps({"run_id": args.run_id, "invalidated": sorted(affected), "run_status": state["status"]}))


def cmd_safe_stop(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        if state["status"] in TERMINAL_RUN_STATES:
            raise WorkflowError(f"Run is already terminal: {state['status']}")
        state["status"] = "safe_stopped"
        state["safe_stop_reason"] = args.reason
        state["completed_at"] = now()
        state["updated_at"] = now()
        event(directory, "run.safe_stopped", args.actor, {"reason": args.reason})
        atomic_json(directory / "state.json", state)
        print(json.dumps({"run_id": args.run_id, "status": state["status"]}))


def cmd_rollback(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        node = state["nodes"].get(args.node)
        if not node:
            raise WorkflowError(f"Unknown node: {args.node}")
        if node["status"] not in {"completed", "failed"}:
            raise WorkflowError(f"Node cannot be rolled back from {node['status']}")
        if not args.verification:
            raise WorkflowError("Rollback requires verification evidence")
        if args.git_ref and git_value("cat-file", "-t", args.git_ref) != "commit":
            raise WorkflowError("Rollback git_ref is not a valid commit")
        node["status"] = "rolled_back"
        state["status"] = "rolled_back"
        state["completed_at"] = now()
        state["updated_at"] = now()
        details = {
            "node": args.node,
            "strategy": args.strategy,
            "git_ref": args.git_ref,
            "reason": args.reason,
            "verification": args.verification,
        }
        event(directory, "node.rolled_back", args.actor, details)
        event(directory, "run.rolled_back", "orchestrator", details)
        atomic_json(directory / "state.json", state)
        print(json.dumps({"run_id": args.run_id, "node": args.node, "status": state["status"]}))


def load_events(directory: Path) -> list[dict[str, Any]]:
    path = directory / "events.jsonl"
    if not path.exists():
        return []
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    previous_hash = None
    for item in events:
        event_hash = item.get("event_hash")
        unsigned = {key: value for key, value in item.items() if key != "event_hash"}
        expected = hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest()
        if item.get("previous_hash") != previous_hash or event_hash != expected:
            raise WorkflowError("Event ledger hash chain validation failed")
        previous_hash = event_hash
    return events


def cmd_status(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (_, state):
        ready = [node_id for node_id, node in state["nodes"].items() if node["status"] == "ready"]
        waiting = [node_id for node_id, node in state["nodes"].items() if node["status"] == "waiting_approval"]
        print(json.dumps({"run_id": args.run_id, "status": state["status"], "ready": ready, "waiting": waiting}))


def cmd_handoff(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        node = state["nodes"].get(args.node)
        if not node or node["status"] != "ready":
            raise WorkflowError("Handoff is available only for a ready node")
        upstream = {}
        for dependency in node["depends_on"]:
            dependency_node = state["nodes"][dependency]
            matches = sorted((directory / "nodes").glob(f"{dependency}-attempt-*.json"))
            upstream[dependency] = {
                "status": dependency_node["status"],
                "output_hash": dependency_node["output_hash"],
                "result": read_json(matches[-1]) if matches else None,
            }
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "requirement": state["requirement"],
                    "node": args.node,
                    "agent": node["agent"],
                    "entry_gate": node.get("entry_gate"),
                    "exit_gate": node["exit_gate"],
                    "upstream": upstream,
                },
                indent=2,
                sort_keys=True,
            )
        )


def calculate_metrics(directory: Path, state: dict[str, Any]) -> dict[str, Any]:
    events = load_events(directory)
    retries = sum(item["event"] == "node.retry_scheduled" for item in events)
    rollbacks = sum(item["event"] == "run.rolled_back" for item in events)
    failures = [item for item in events if item["event"] == "node.failed"]
    mttr: float | None = None
    if failures:
        failure_time = datetime.fromisoformat(failures[0]["timestamp"])
        failed_node = failures[0]["details"]["node"]
        recovery = next(
            (
                datetime.fromisoformat(item["timestamp"])
                for item in events
                if datetime.fromisoformat(item["timestamp"]) >= failure_time
                and (
                    (item["event"] == "node.completed" and item["details"].get("node") == failed_node)
                    or item["event"] == "run.rolled_back"
                )
            ),
            None,
        )
        if recovery:
            mttr = round((recovery - failure_time).total_seconds(), 3)
    end = datetime.fromisoformat(state["completed_at"] or now())
    start = datetime.fromisoformat(state["started_at"])
    attempts = sum(node.get("execution_count", node["attempts"]) for node in state["nodes"].values())
    return {
        "run_id": state["run_id"],
        "status": state["status"],
        "successful": state["status"] == "completed",
        "node_attempts": attempts,
        "retry_count": retries,
        "retry_frequency": round(retries / attempts, 4) if attempts else 0.0,
        "rollback_count": rollbacks,
        "rollback_frequency": round(rollbacks / attempts, 4) if attempts else 0.0,
        "safe_stop_count": int(state["status"] == "safe_stopped"),
        "replan_count": state["replan_count"],
        "end_to_end_latency_seconds": round((end - start).total_seconds(), 3),
        "mttr_seconds": mttr,
    }


def cmd_metrics(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        metrics = calculate_metrics(directory, state)
        atomic_json(directory / "metrics.json", metrics)
        print(json.dumps(metrics, indent=2, sort_keys=True))


def cmd_aggregate_metrics(_: argparse.Namespace) -> None:
    per_run = []
    if RUNS_ROOT.exists():
        for directory in sorted(RUNS_ROOT.iterdir()):
            state_path = directory / "state.json"
            if state_path.exists():
                per_run.append(calculate_metrics(directory, read_json(state_path)))
    terminal = [item for item in per_run if item["status"] in TERMINAL_RUN_STATES]
    latencies = [item["end_to_end_latency_seconds"] for item in terminal]
    recovery_times = [item["mttr_seconds"] for item in terminal if item["mttr_seconds"] is not None]
    total_attempts = sum(item["node_attempts"] for item in per_run)
    total_retries = sum(item["retry_count"] for item in per_run)
    total_rollbacks = sum(item["rollback_count"] for item in per_run)
    total_safe_stops = sum(item["safe_stop_count"] for item in per_run)
    aggregate = {
        "total_runs": len(per_run),
        "terminal_runs": len(terminal),
        "success_rate": round(sum(item["successful"] for item in terminal) / len(terminal), 4) if terminal else None,
        "node_attempts": total_attempts,
        "retry_count": total_retries,
        "retry_frequency": round(total_retries / total_attempts, 4) if total_attempts else 0.0,
        "rollback_count": total_rollbacks,
        "rollback_frequency": round(total_rollbacks / total_attempts, 4) if total_attempts else 0.0,
        "safe_stop_count": total_safe_stops,
        "safe_stop_frequency": round(total_safe_stops / len(terminal), 4) if terminal else None,
        "replan_count": sum(item["replan_count"] for item in per_run),
        "mean_end_to_end_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "mean_time_to_recovery_seconds": round(sum(recovery_times) / len(recovery_times), 3)
        if recovery_times
        else None,
        "runs": per_run,
    }
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(RUNS_ROOT / "aggregate-metrics.json", aggregate)
    print(json.dumps(aggregate, indent=2, sort_keys=True))


def cmd_summary(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        metrics = calculate_metrics(directory, state)
        completed = [node_id for node_id, node in state["nodes"].items() if node["status"] == "completed"]
        unresolved = [
            f"{node_id}: {node['status']}"
            for node_id, node in state["nodes"].items()
            if node["status"] not in {"completed", "skipped"}
        ]
        outputs = []
        for path in sorted((directory / "nodes").glob("*.json")):
            result = read_json(path)
            if result.get("status") == "completed":
                outputs.append((path.stem, result))
        artifacts = sorted({item for _, result in outputs for item in result["artifacts"]})
        evidence = sorted({item for _, result in outputs for item in result["evidence"]})
        decisions = [item for _, result in outputs for item in result["decisions"]]
        risks = [item for _, result in outputs for item in result["risks"]]
        assumptions = [item for _, result in outputs for item in result["assumptions"]]
        approvals = [item for item in load_events(directory) if item["event"] == "gate.approved"]
        lines = [
            f"# Engineering summary: {state['run_id']}",
            "",
            "## Requirement",
            "",
            state["requirement"],
            "",
            "## Outcome",
            "",
            f"- Scenario: `{state['scenario']}`",
            f"- Traits: {', '.join(state.get('traits', []))}",
            f"- Status: `{state['status']}`",
            f"- Git baseline: `{state['git_ref_at_start'] or 'uncommitted baseline'}`",
            f"- Completed stages: {', '.join(completed) or 'none'}",
            f"- Safe-stop reason: {state['safe_stop_reason'] or 'none'}",
            "",
            "## Validation and reliability",
            "",
            f"- Attempts: {metrics['node_attempts']}",
            f"- Retries: {metrics['retry_count']}",
            f"- Rollbacks: {metrics['rollback_count']}",
            f"- Replans: {metrics['replan_count']}",
            f"- End-to-end latency: {metrics['end_to_end_latency_seconds']} seconds",
            f"- MTTR: {metrics['mttr_seconds'] if metrics['mttr_seconds'] is not None else 'unavailable'}",
            "",
            "## Decisions and rationale",
            "",
            *(f"- {item}" for item in decisions or ["No decisions recorded."]),
            "",
            "## Artifacts",
            "",
            *(f"- `{item}`" for item in artifacts or ["No artifacts recorded."]),
            "",
            "## Validation evidence",
            "",
            *(f"- {item}" for item in evidence or ["No validation evidence recorded."]),
            "",
            "## Risks, assumptions, limitations, and unresolved items",
            "",
            *(f"- Risk: {item}" for item in risks),
            *(f"- Assumption: {item}" for item in assumptions),
            *(f"- {item}" for item in unresolved),
            "- Limitation: local files are trusted-operator evidence, not tamper-proof audit storage.",
            "",
            "## Approvals and rollback readiness",
            "",
            *(
                f"- {item['details']['node']}: {item['details']['actor']} ({item['details']['role']})"
                for item in approvals
            ),
            "- Rollback strategy is recorded at implementation; execution requires verified operator evidence.",
        ]
        (directory / "final-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        atomic_json(directory / "metrics.json", metrics)
        event(
            directory,
            "summary.generated",
            "orchestrator",
            {"path": display_path(directory / "final-summary.md")},
        )
        print(directory / "final-summary.md")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--scenario", required=True, choices=["greenfield", "brownfield", "ambiguous"])
    start.add_argument("--requirement-file", required=True)
    start.add_argument("--run-id")
    start.add_argument("--baseline-ref")
    start.add_argument("--trait", action="append", choices=["brownfield", "ambiguous"], default=[])
    start.set_defaults(handler=cmd_start)

    transition = commands.add_parser("transition")
    transition.add_argument("--run-id", required=True)
    transition.add_argument("--node", required=True)
    transition.add_argument("--status", required=True, choices=["running", "completed", "failed", "needs_input"])
    transition.add_argument("--actor", required=True)
    transition.add_argument("--result")
    transition.add_argument("--transient", action="store_true")
    transition.set_defaults(handler=cmd_transition)

    approve = commands.add_parser("approve")
    approve.add_argument("--run-id", required=True)
    approve.add_argument("--node", required=True)
    approve.add_argument("--decision", required=True, choices=["approved", "rejected"])
    approve.add_argument("--actor", required=True)
    approve.add_argument("--role", required=True, choices=["owner", "reviewer", "release-manager"])
    approve.add_argument("--comment", default="")
    approve.set_defaults(handler=cmd_approve)

    replan = commands.add_parser("replan")
    replan.add_argument("--run-id", required=True)
    replan.add_argument("--changed-node", required=True)
    replan.add_argument("--actor", required=True)
    replan.add_argument("--reason", required=True)
    replan.add_argument("--new-output-hash")
    replan.set_defaults(handler=cmd_replan)

    safe_stop = commands.add_parser("safe-stop")
    safe_stop.add_argument("--run-id", required=True)
    safe_stop.add_argument("--actor", required=True)
    safe_stop.add_argument("--reason", required=True)
    safe_stop.set_defaults(handler=cmd_safe_stop)

    rollback = commands.add_parser("rollback")
    rollback.add_argument("--run-id", required=True)
    rollback.add_argument("--node", required=True)
    rollback.add_argument("--actor", required=True)
    rollback.add_argument("--strategy", required=True)
    rollback.add_argument("--git-ref")
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--verification", required=True)
    rollback.set_defaults(handler=cmd_rollback)

    metrics = commands.add_parser("metrics")
    metrics.add_argument("--run-id", required=True)
    metrics.set_defaults(handler=cmd_metrics)

    aggregate_metrics = commands.add_parser("aggregate-metrics")
    aggregate_metrics.set_defaults(handler=cmd_aggregate_metrics)

    summary = commands.add_parser("summary")
    summary.add_argument("--run-id", required=True)
    summary.set_defaults(handler=cmd_summary)

    status = commands.add_parser("status")
    status.add_argument("--run-id", required=True)
    status.set_defaults(handler=cmd_status)

    handoff = commands.add_parser("handoff")
    handoff.add_argument("--run-id", required=True)
    handoff.add_argument("--node", required=True)
    handoff.set_defaults(handler=cmd_handoff)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        args.handler(args)
        return 0
    except (WorkflowError, OSError, ValueError, yaml.YAMLError) as error:
        print(f"workflow error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
