from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(".agents/skills/agentic-sdlc/scripts/workflow.py").resolve()


@pytest.fixture
def workflow(tmp_path: Path):
    spec = importlib.util.spec_from_file_location("workflow_helper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    module.RUNS_ROOT = tmp_path / "runs"
    return module


def args(**values):
    return argparse.Namespace(**values)


def result_file(tmp_path: Path, status: str, summary: str = "evidence accepted") -> Path:
    path = tmp_path / f"result-{status}-{len(list(tmp_path.glob('result-*')))}.json"
    path.write_text(
        json.dumps(
            {
                "status": status,
                "summary": summary,
                "artifacts": [],
                "evidence": ["pytest"],
                "decisions": [],
                "risks": [],
                "assumptions": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def start(workflow, tmp_path: Path, run_id: str = "test-run", scenario: str = "greenfield") -> Path:
    requirement = tmp_path / "requirement.md"
    requirement.write_text("Build a tested URL shortener service.", encoding="utf-8")
    workflow.cmd_start(args(scenario=scenario, requirement_file=str(requirement), run_id=run_id))
    return workflow.RUNS_ROOT / run_id


def complete(workflow, tmp_path: Path, run_id: str, node: str, actor: str = "test-agent") -> None:
    workflow.cmd_transition(args(run_id=run_id, node=node, status="running", actor=actor, result=None, transient=False))
    output = result_file(tmp_path, "completed")
    workflow.cmd_transition(
        args(run_id=run_id, node=node, status="completed", actor=actor, result=str(output), transient=False)
    )


def test_full_graph_with_parallel_join_retry_and_approvals(workflow, tmp_path: Path) -> None:
    directory = start(workflow, tmp_path)
    complete(workflow, tmp_path, "test-run", "intake")
    complete(workflow, tmp_path, "test-run", "requirements")
    complete(workflow, tmp_path, "test-run", "architecture")
    state = workflow.read_json(directory / "state.json")
    assert state["nodes"]["design_approval"]["status"] == "waiting_approval"

    workflow.cmd_approve(
        args(run_id="test-run", node="design_approval", decision="approved", actor="human-reviewer", comment="approved")
    )
    complete(workflow, tmp_path, "test-run", "implementation")

    workflow.cmd_transition(
        args(run_id="test-run", node="test_review", status="running", actor="test-agent", result=None, transient=False)
    )
    failed = result_file(tmp_path, "failed", "temporary test runner outage")
    workflow.cmd_transition(
        args(
            run_id="test-run",
            node="test_review",
            status="failed",
            actor="test-agent",
            result=str(failed),
            transient=True,
        )
    )
    complete(workflow, tmp_path, "test-run", "test_review")
    complete(workflow, tmp_path, "test-run", "security_review")
    complete(workflow, tmp_path, "test-run", "documentation_review")
    complete(workflow, tmp_path, "test-run", "release_review")
    workflow.cmd_approve(
        args(run_id="test-run", node="release_approval", decision="approved", actor="human-reviewer", comment="ship")
    )
    complete(workflow, tmp_path, "test-run", "final_summary")
    workflow.cmd_metrics(args(run_id="test-run"))
    workflow.cmd_summary(args(run_id="test-run"))

    state = workflow.read_json(directory / "state.json")
    metrics = workflow.read_json(directory / "metrics.json")
    assert state["status"] == "completed"
    assert metrics["retry_count"] == 1
    assert metrics["mttr_seconds"] is not None
    assert (directory / "final-summary.md").exists()


def test_replan_invalidates_only_downstream_nodes(workflow, tmp_path: Path) -> None:
    directory = start(workflow, tmp_path, run_id="replan-run")
    complete(workflow, tmp_path, "replan-run", "intake")
    complete(workflow, tmp_path, "replan-run", "requirements")
    complete(workflow, tmp_path, "replan-run", "architecture")

    workflow.cmd_replan(
        args(
            run_id="replan-run",
            changed_node="requirements",
            actor="human-reviewer",
            reason="Acceptance criteria changed",
        )
    )
    state = workflow.read_json(directory / "state.json")
    assert state["nodes"]["requirements"]["status"] == "completed"
    assert state["nodes"]["architecture"]["status"] == "ready"
    assert state["nodes"]["implementation"]["status"] == "invalidated"
    assert state["replan_count"] == 1


def test_rejected_gate_safe_stops(workflow, tmp_path: Path) -> None:
    directory = start(workflow, tmp_path, run_id="rejected-run")
    complete(workflow, tmp_path, "rejected-run", "intake")
    complete(workflow, tmp_path, "rejected-run", "requirements")
    complete(workflow, tmp_path, "rejected-run", "architecture")
    workflow.cmd_approve(
        args(
            run_id="rejected-run", node="design_approval", decision="rejected", actor="human-reviewer", comment="unsafe"
        )
    )
    assert workflow.read_json(directory / "state.json")["status"] == "safe_stopped"
