#!/usr/bin/env python3
"""Deterministic state, audit, gate, replan, and metrics helper for the SDLC skill."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
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


def graph() -> dict[str, Any]:
    with GRAPH_PATH.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), dict):
        raise WorkflowError("Invalid workflow graph")
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
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": now(),
        "event": event_type,
        "actor": actor,
        "details": details,
    }
    with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def condition_applies(condition: str | None, scenario: str) -> bool:
    if condition is None:
        return True
    return {
        "material_ambiguity_present": scenario == "ambiguous",
        "brownfield": scenario == "brownfield",
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
    definition = graph()
    run_id = args.run_id or f"{args.scenario}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    directory = run_dir(run_id)
    if directory.exists():
        raise WorkflowError(f"Run already exists: {run_id}")
    directory.mkdir(parents=True)
    (directory / "nodes").mkdir()
    started = now()
    nodes: dict[str, Any] = {}
    for node_id, node_definition in definition["nodes"].items():
        applicable = condition_applies(node_definition.get("condition"), args.scenario)
        nodes[node_id] = {
            **node_definition,
            "id": node_id,
            "status": "pending" if applicable else "skipped",
            "attempts": 0,
            "output_hash": None,
            "last_error": None,
        }
    state = {
        "run_id": run_id,
        "scenario": args.scenario,
        "requirement": requirement,
        "requirement_hash": hashlib.sha256(requirement.encode()).hexdigest(),
        "status": "running",
        "graph_name": definition["name"],
        "graph_version": definition["version"],
        "replan_count": 0,
        "git_ref_at_start": git_ref(),
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
    return result


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
            node["status"] = "running"
            event(directory, "node.started", args.actor, {"node": args.node, "attempt": node["attempts"]})
        else:
            if node["status"] != "running":
                raise WorkflowError(f"Node cannot finish from {node['status']}")
            if not args.result:
                raise WorkflowError("A structured --result file is required")
            result = validate_result(Path(args.result))
            if result["status"] != args.status:
                raise WorkflowError("Command status and result status differ")
            destination = directory / "nodes" / f"{args.node}-attempt-{node['attempts']}.json"
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
                        "attempt": node["attempts"],
                        "output": display_path(destination),
                        "output_hash": output_hash,
                    },
                )
            elif args.status == "needs_input":
                node["status"] = "failed"
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
                        "attempt": node["attempts"],
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
        record = {
            "node": args.node,
            "decision": args.decision,
            "actor": args.actor,
            "comment": args.comment,
            "timestamp": now(),
            "upstream_hashes": {
                dependency: state["nodes"][dependency]["output_hash"] for dependency in node["depends_on"]
            },
        }
        event(directory, f"gate.{args.decision}", args.actor, record)
        node["attempts"] += 1
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
        for node_id in affected:
            node = state["nodes"][node_id]
            if node["status"] != "skipped":
                node["status"] = "invalidated"
                node["output_hash"] = None
                node["last_error"] = None
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


def load_events(directory: Path) -> list[dict[str, Any]]:
    path = directory / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def calculate_metrics(directory: Path, state: dict[str, Any]) -> dict[str, Any]:
    events = load_events(directory)
    retries = sum(item["event"] == "node.retry_scheduled" for item in events)
    rollbacks = sum(item["event"] in {"node.rolled_back", "run.rolled_back"} for item in events)
    failures = [item for item in events if item["event"] == "node.failed"]
    recovery_events = [item for item in events if item["event"] in {"node.completed", "run.rolled_back"}]
    mttr: float | None = None
    if failures and recovery_events:
        failure_time = datetime.fromisoformat(failures[0]["timestamp"])
        recovery = next(
            (
                datetime.fromisoformat(item["timestamp"])
                for item in recovery_events
                if datetime.fromisoformat(item["timestamp"]) >= failure_time
            ),
            None,
        )
        if recovery:
            mttr = round((recovery - failure_time).total_seconds(), 3)
    end = datetime.fromisoformat(state["completed_at"] or now())
    start = datetime.fromisoformat(state["started_at"])
    attempts = sum(node["attempts"] for node in state["nodes"].values())
    return {
        "run_id": state["run_id"],
        "status": state["status"],
        "successful": state["status"] == "completed",
        "node_attempts": attempts,
        "retry_count": retries,
        "retry_frequency": round(retries / attempts, 4) if attempts else 0.0,
        "rollback_count": rollbacks,
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


def cmd_summary(args: argparse.Namespace) -> None:
    with locked_run(args.run_id) as (directory, state):
        metrics = calculate_metrics(directory, state)
        completed = [node_id for node_id, node in state["nodes"].items() if node["status"] == "completed"]
        unresolved = [
            f"{node_id}: {node['status']}"
            for node_id, node in state["nodes"].items()
            if node["status"] not in {"completed", "skipped"}
        ]
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
            "## Risks, assumptions, limitations, and unresolved items",
            "",
            *(f"- {item}" for item in unresolved),
        ]
        if not unresolved:
            lines.append("- See node artifacts for recorded risks, assumptions, decisions, and evidence.")
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
    approve.add_argument("--comment", default="")
    approve.set_defaults(handler=cmd_approve)

    replan = commands.add_parser("replan")
    replan.add_argument("--run-id", required=True)
    replan.add_argument("--changed-node", required=True)
    replan.add_argument("--actor", required=True)
    replan.add_argument("--reason", required=True)
    replan.set_defaults(handler=cmd_replan)

    safe_stop = commands.add_parser("safe-stop")
    safe_stop.add_argument("--run-id", required=True)
    safe_stop.add_argument("--actor", required=True)
    safe_stop.add_argument("--reason", required=True)
    safe_stop.set_defaults(handler=cmd_safe_stop)

    metrics = commands.add_parser("metrics")
    metrics.add_argument("--run-id", required=True)
    metrics.set_defaults(handler=cmd_metrics)

    summary = commands.add_parser("summary")
    summary.add_argument("--run-id", required=True)
    summary.set_defaults(handler=cmd_summary)
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
