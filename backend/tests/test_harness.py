"""End-to-end runs with MockLLM. Scores come from the workspace, not a fixture table."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from forge.db import Database
from forge.service import ForgeService
from forge.settings import EXAMPLE_REPO

SIMPLE = (
    "I am not a programmer. Please add a way to mark a todo as done.\n"
    "When a todo is marked done, its done flag becomes true.\n"
    "Keep add, list, get, and remove working.\n"
    "Add a unit test for marking a todo done."
)


def _service(tmp_path: Path) -> ForgeService:
    return ForgeService(Database(tmp_path / "forge.db"), workspace_root=tmp_path)


def _run(service: ForgeService, config: str, goal: str) -> dict:
    repo = service.connect_local(str(EXAMPLE_REPO), name="todo-api")
    service.index(repo["id"])
    created = service.create_run(repo_id=repo["id"], config_name=config, goal=goal)
    return asyncio.run(service.execute(created["id"]))


def _probe(workspace: Path) -> dict:
    script = """
import json
from todo.store import TodoStore
store = TodoStore()
item = store.add("a")
try:
    done = store.mark_done(item["id"])["done"]
except Exception:
    done = None
print(json.dumps({"done": done, "has_remove": hasattr(store, "remove")}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
        env={**dict(**__import__("os").environ), "PYTHONPATH": str(workspace)},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_baseline_forgets_remove_and_does_not_mark_done(tmp_path: Path):
    finished = _run(_service(tmp_path), "baseline", SIMPLE)
    assert finished["status"] in {"completed", "completed_with_failures"}
    assert finished["metrics"]["verification_pass_rate"] is None
    probe = _probe(Path(finished["workspace"]))
    assert probe["done"] is not True
    assert probe["has_remove"] is False
    assert finished["metrics"]["tokens"] > 0
    assert finished["metrics"]["tool_calls"] >= 1


def test_full_forge_simple_marks_done_and_keeps_remove(tmp_path: Path):
    finished = _run(_service(tmp_path), "full_forge", SIMPLE)
    assert finished["error"] in (None, "")
    assert finished["status"] == "completed"
    probe = _probe(Path(finished["workspace"]))
    assert probe["done"] is True
    assert probe["has_remove"] is True
    assert finished["metrics"]["verification_pass_rate"] == 1
    assert finished["plan"]["tasks"]
    assert finished["tasks"]
    assert finished["llm_calls"]
    assert finished["branch"].startswith("forge/run-")
