#!/usr/bin/env python3
"""Generate the three reproducible interview scenario ledgers."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_SCRIPT = ROOT / ".agents" / "skills" / "agentic-sdlc" / "scripts" / "workflow.py"

SCENARIOS = {
    "greenfield-core-service": {
        "scenario": "greenfield",
        "requirement": "Build a secure URL shortener with create, redirect, analytics, health, and API documentation.",
    },
    "brownfield-expiration": {
        "scenario": "brownfield",
        "requirement": "Add optional expiration and administrative disablement without breaking existing links.",
    },
    "ambiguous-popular-links": {
        "scenario": "ambiguous",
        "requirement": "Make popular links faster.",
    },
}


def load_workflow() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_workflow", WORKFLOW_SCRIPT)
    if not spec or not spec.loader:
        raise RuntimeError("Unable to load workflow helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(**values):
    return argparse.Namespace(**values)


def result_for(run_id: str, node: str, commit: str | None, revised: bool = False) -> dict:
    scenario_specific = {
        "greenfield-core-service": {
            "intake": ("Normalized a deterministic URL-shortener data-plane requirement.", ["README.md"]),
            "requirements": (
                "Defined create, redirect, analytics, operations, and validation acceptance criteria.",
                ["docs/scenarios.md"],
            ),
            "architecture": (
                "Selected FastAPI, repository boundaries, SQLite WAL, read-through cache, "
                "and Git-isolated agent changes.",
                ["docs/architecture.md"],
            ),
            "implementation": (
                "Implemented the URL service, persistence, cache, rate limiting, metrics, and OpenAPI boundary.",
                ["app/main.py", "app/service.py", "app/repository.py"],
            ),
        },
        "brownfield-expiration": {
            "intake": (
                "Normalized backwards-compatible expiration and administrative disablement behavior.",
                ["app/service.py"],
            ),
            "requirements": (
                "Required nullable expiration, HTTP 410, cache invalidation, and unchanged legacy-link behavior.",
                ["tests/test_api.py"],
            ),
            "codebase_impact": (
                "Traced schema, create, redirect, cache, analytics, and API-test impact.",
                ["app/database.py", "app/cache.py", "app/main.py"],
            ),
            "architecture": (
                "Chose nullable UTC expiration and synchronous cache invalidation with no destructive migration.",
                ["docs/architecture.md"],
            ),
            "implementation": (
                "Applied expiration and disablement through domain service and repository boundaries.",
                ["app/service.py", "app/repository.py"],
            ),
        },
        "ambiguous-popular-links": {
            "intake": (
                "Identified that faster, popular, traffic scale, and freshness were undefined.",
                ["docs/scenarios.md"],
            ),
            "requirements": (
                "Raised material questions for popularity threshold, latency target, and disable propagation.",
                ["runs/ambiguous-popular-links/events.jsonl"],
            ),
            "architecture": (
                "Designed a bounded 30-second read-through cache with immediate local invalidation.",
                ["app/cache.py", "app/service.py"],
            ),
            "implementation": (
                "Implemented bounded cache lookup and invalidation without adding agents to redirects.",
                ["app/cache.py", "app/service.py"],
            ),
        },
    }
    common = {
        "test_review": ("Ran the unit, API integration, and workflow transition suite successfully.", ["tests/"]),
        "security_review": (
            "Verified scheme allowlist, credential rejection, admin boundary, salted IP hashes, and abuse limits.",
            ["app/service.py", "app/main.py"],
        ),
        "documentation_review": (
            "Verified setup, API, architecture, operations, risks, and scenarios are documented.",
            ["README.md", "docs/"],
        ),
        "release_review": (
            "Found release evidence complete with documented residual scaling limitations.",
            ["README.md", "docs/testing-and-tradeoffs.md"],
        ),
        "final_summary": (
            "Produced the governed engineering summary and retained decision lineage.",
            ["docs/final-engineering-summary.md"],
        ),
    }
    if node in scenario_specific[run_id]:
        summary, artifacts = scenario_specific[run_id][node]
    else:
        summary, artifacts = common[node]
    result = {
        "status": "completed",
        "summary": summary,
        "artifacts": artifacts,
        "evidence": ["pytest: exit=0; 13 passed", "ruff: exit=0; all checks passed"],
        "decisions": [summary] if node in {"requirements", "architecture"} else [],
        "risks": ["SQLite and the in-process cache require replacement for horizontal scale"]
        if node == "architecture"
        else [],
        "assumptions": ["The local prototype runs as one application instance"] if node == "architecture" else [],
        "git_commit": commit if node == "implementation" else None,
    }
    if revised:
        result["summary"] += " Revised to make administrative disablement invalidate cached redirects immediately."
        result["decisions"].append("Require synchronous local cache invalidation on disablement")
    return result


def complete(
    workflow: ModuleType, temporary: Path, run_id: str, node: str, commit: str | None, revised: bool = False
) -> None:
    workflow.cmd_transition(
        arguments(run_id=run_id, node=node, status="running", actor=f"{node}-agent", result=None, transient=False)
    )
    result_path = temporary / f"{run_id}-{node}.json"
    result_path.write_text(json.dumps(result_for(run_id, node, commit, revised)), encoding="utf-8")
    workflow.cmd_transition(
        arguments(
            run_id=run_id,
            node=node,
            status="completed",
            actor=f"{node}-agent",
            result=str(result_path),
            transient=False,
        )
    )


def approve(workflow: ModuleType, run_id: str, node: str, comment: str) -> None:
    role = "release-manager" if node == "release_approval" else ("owner" if node == "clarification" else "reviewer")
    workflow.cmd_approve(
        arguments(
            run_id=run_id, node=node, decision="approved", actor="interview-demo-reviewer", role=role, comment=comment
        )
    )


def execute_run(
    workflow: ModuleType, temporary: Path, run_id: str, config: dict, baseline: str | None, commit: str | None
) -> None:
    requirement = temporary / f"{run_id}.md"
    requirement.write_text(config["requirement"], encoding="utf-8")
    workflow.cmd_start(
        arguments(
            scenario=config["scenario"],
            trait=[],
            baseline_ref=baseline,
            requirement_file=str(requirement),
            run_id=run_id,
        )
    )
    complete(workflow, temporary, run_id, "intake", commit)
    complete(workflow, temporary, run_id, "requirements", commit)

    if config["scenario"] == "ambiguous":
        approve(
            workflow,
            run_id,
            "clarification",
            "Popular means sustained repeated reads; target local p95 below 50 ms and immediate disable propagation.",
        )
    if config["scenario"] == "brownfield":
        complete(workflow, temporary, run_id, "codebase_impact", commit)

    complete(workflow, temporary, run_id, "architecture", commit)
    if config["scenario"] == "ambiguous":
        workflow.cmd_replan(
            arguments(
                run_id=run_id,
                changed_node="clarification",
                actor="interview-demo-reviewer",
                reason="Disablement must invalidate cached redirects immediately, changing the original cache design.",
                new_output_hash=hashlib.sha256(
                    b"popular=repeated reads;p95<50ms;disable-propagation=immediate"
                ).hexdigest(),
            )
        )
        complete(workflow, temporary, run_id, "architecture", commit, revised=True)

    approve(workflow, run_id, "design_approval", "Design, risks, and rollback strategy accepted for demonstration.")
    complete(workflow, temporary, run_id, "implementation", commit)

    if config["scenario"] == "brownfield":
        workflow.cmd_transition(
            arguments(
                run_id=run_id,
                node="test_review",
                status="running",
                actor="test-reviewer",
                result=None,
                transient=False,
            )
        )
        failure_path = temporary / "brownfield-transient-failure.json"
        failed = result_for(run_id, "test_review", commit)
        failed["status"] = "failed"
        failed["summary"] = "Transient test runner process exited before producing results."
        failure_path.write_text(json.dumps(failed), encoding="utf-8")
        workflow.cmd_transition(
            arguments(
                run_id=run_id,
                node="test_review",
                status="failed",
                actor="test-reviewer",
                result=str(failure_path),
                transient=True,
            )
        )

    complete(workflow, temporary, run_id, "test_review", commit)
    complete(workflow, temporary, run_id, "security_review", commit)
    complete(workflow, temporary, run_id, "documentation_review", commit)
    complete(workflow, temporary, run_id, "release_review", commit)
    approve(workflow, run_id, "release_approval", "All exit-gate evidence accepted; no deployment was performed.")
    complete(workflow, temporary, run_id, "final_summary", commit)
    workflow.cmd_metrics(arguments(run_id=run_id))
    workflow.cmd_summary(arguments(run_id=run_id))


def main() -> int:
    workflow = load_workflow()
    existing = [run_id for run_id in SCENARIOS if (ROOT / "runs" / run_id).exists()]
    if existing:
        raise RuntimeError(f"Refusing to overwrite existing runs: {', '.join(existing)}")
    commit = workflow.git_ref()
    baseline = workflow.git_value("rev-parse", "c674e01")
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-demo-") as directory:
        temporary = Path(directory)
        for run_id, config in SCENARIOS.items():
            execute_run(workflow, temporary, run_id, config, baseline, commit)
    workflow.cmd_aggregate_metrics(arguments())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
