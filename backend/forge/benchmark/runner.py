"""Run the slide matrix: config × difficulty, measured not hard-coded."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from forge.service import ForgeService
from forge.settings import BENCHMARK_ORACLES, ROOT, load_benchmark_tasks
from forge.util import new_id, utc_now


def _pytest_counts(workspace: Path, targets: list[str]) -> dict[str, int]:
    if not targets:
        return {"passed": 0, "failed": 0, "errors": 0, "total": 0}
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(workspace)
    env.pop("PYTEST_ADDOPTS", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "--noconftest", f"--rootdir={workspace}", f"--confcutdir={workspace}", *targets],
        cwd=str(workspace),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    passed = _count(output, r"(\d+) passed")
    failed = _count(output, r"(\d+) failed")
    errors = _count(output, r"(\d+) error")
    # Quiet pytest sometimes prints only the progress glyphs (`.` pass, `F` fail).
    if passed == failed == errors == 0:
        passed, failed, errors = _glyphs(output)
    if proc.returncode != 0 and passed == failed == errors == 0:
        errors = 1
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
    }


def _glyphs(output: str) -> tuple[int, int, int]:
    passed = failed = errors = 0
    found = False
    for line in output.splitlines():
        body = line.split("[", 1)[0].strip()
        if not body or any(ch not in ".FEsxX" for ch in body):
            continue
        if not any(ch in body for ch in ".FE"):
            continue
        found = True
        passed += body.count(".")
        failed += body.count("F")
        errors += body.count("E")
    if not found:
        return 0, 0, 0
    return passed, failed, errors


def _count(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


def _rate(part: float, whole: float) -> float | None:
    if not whole:
        return None
    return round(part / whole, 4)


async def run_benchmark(
    service: ForgeService,
    *,
    repo_id: str,
    config_names: list[str],
    task_ids: list[str] | None = None,
    llm_override: dict[str, Any] | None = None,
    sandbox: str = "repo",
    context_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = service.db.get_repo_raw(repo_id)
    if not repo:
        raise KeyError(repo_id)
    specs = load_benchmark_tasks()
    if task_ids:
        wanted = set(task_ids)
        specs = [spec for spec in specs if spec.get("id") in wanted]
    bench_id = new_id("bench")
    service.db.insert_benchmark(
        {
            "id": bench_id,
            "repo_id": repo_id,
            "status": "running",
            "created_at": utc_now(),
            "ended_at": None,
            "summary": {"configs": config_names, "tasks": [spec.get("id") for spec in specs]},
        }
    )
    source = Path(repo["path"])
    from forge.core.checkpoints import user_base

    base = None if sandbox == "docker" else user_base(source)
    cells = []
    for spec in specs:
        pre = _pytest_counts(source, ["tests/test_store.py"])
        for config_name in config_names:
            created = service.create_run(
                repo_id=repo_id,
                config_name=config_name,
                goal=spec["prompt"],
                llm_override=llm_override,
                interactive=False,
                sandbox=sandbox,
                context_policy=context_policy,
                base_rev=base,
            )
            finished = await service.execute(created["id"])
            workspace = Path(finished["workspace"]) if finished.get("workspace") else source
            post = _pytest_counts(workspace, ["tests/test_store.py"]) if workspace.exists() else pre
            oracle_path = str(BENCHMARK_ORACLES / spec["oracle"])
            oracle = _pytest_counts(workspace, [oracle_path]) if workspace.exists() else {"passed": 0, "total": 0}
            metrics = dict(finished.get("metrics") or {})
            pre_passed = pre["passed"]
            post_passed = post["passed"]
            regression = 0.0 if not pre_passed else round(max(0, pre_passed - post_passed) / pre_passed, 4)
            cell_metrics = {
                "task_completion": _rate(oracle["passed"], oracle["total"]) or 0.0,
                "oracle_passed": oracle["passed"],
                "oracle_total": oracle["total"],
                "recovery_success": metrics.get("recovery_success"),
                "verification_pass_rate": metrics.get("verification_pass_rate"),
                "regression_rate": regression,
                "human_intervention_rate": 1.0 if metrics.get("human_intervention") else 0.0,
                "harness_status": finished.get("status"),
                "elapsed_ms": metrics.get("elapsed_ms"),
                "tokens": metrics.get("tokens"),
                "pre_passed": pre_passed,
                "post_passed": post_passed,
            }
            cell = {
                "id": new_id("cell"),
                "benchmark_id": bench_id,
                "config_name": config_name,
                "task_id": spec["id"],
                "difficulty": spec.get("difficulty"),
                "run_id": finished["id"],
                "metrics": cell_metrics,
            }
            service.db.add_cell(cell)
            cells.append({**cell, "title": spec.get("title")})
    summary = {"cells": len(cells), "configs": config_names}
    service.db.update_benchmark(bench_id, status="completed", ended_at=utc_now(), summary=summary)
    record = service.db.get_benchmark(bench_id)
    _write_outputs(record)
    return record


def _write_outputs(record: dict[str, Any]) -> None:
    folder = ROOT / "benchmarks" / "results"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"{record['id']}.json"
    csv_path = folder / f"{record['id']}.csv"
    json_path.write_text(json.dumps(record, indent=2))
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "difficulty",
                "task_id",
                "config",
                "task_completion",
                "recovery_success",
                "verification_pass_rate",
                "regression_rate",
                "human_intervention_rate",
                "harness_status",
                "elapsed_ms",
                "tokens",
            ],
        )
        writer.writeheader()
        for cell in record.get("cells") or []:
            metrics = cell.get("metrics") or {}
            writer.writerow(
                {
                    "difficulty": cell.get("difficulty"),
                    "task_id": cell.get("task_id"),
                    "config": cell.get("config_name"),
                    "task_completion": metrics.get("task_completion"),
                    "recovery_success": metrics.get("recovery_success"),
                    "verification_pass_rate": metrics.get("verification_pass_rate"),
                    "regression_rate": metrics.get("regression_rate"),
                    "human_intervention_rate": metrics.get("human_intervention_rate"),
                    "harness_status": metrics.get("harness_status"),
                    "elapsed_ms": metrics.get("elapsed_ms"),
                    "tokens": metrics.get("tokens"),
                }
            )


def format_table(record: dict[str, Any]) -> str:
    rows = ["difficulty        task                      config            complete  verify  recover  regress"]
    for cell in record.get("cells") or []:
        metrics = cell.get("metrics") or {}
        rows.append(
            f"{str(cell.get('difficulty') or ''):<16} "
            f"{str(cell.get('task_id') or ''):<25} "
            f"{str(cell.get('config_name') or ''):<16} "
            f"{_fmt(metrics.get('task_completion')):>8}  "
            f"{_fmt(metrics.get('verification_pass_rate')):>6}  "
            f"{_fmt(metrics.get('recovery_success')):>7}  "
            f"{_fmt(metrics.get('regression_rate')):>7}"
        )
    return "\n".join(rows)


def _fmt(value: Any) -> str:
    if value is None:
        return "   n/a"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)
