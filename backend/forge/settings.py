"""Paths and YAML config loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
ROOT = Path(os.environ.get("FORGE_ROOT", BACKEND_DIR.parent)).resolve()
CONFIG_DIR = ROOT / "configs"
EXAMPLE_REPO = ROOT / "examples" / "todo_api"
BENCHMARK_TASKS = ROOT / "benchmarks" / "tasks"
BENCHMARK_ORACLES = ROOT / "benchmarks" / "oracles"
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "forge.db"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "workspaces").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "clones").mkdir(parents=True, exist_ok=True)
    (ROOT / "benchmarks" / "results").mkdir(parents=True, exist_ok=True)


def list_config_names() -> list[str]:
    return sorted(path.stem for path in CONFIG_DIR.glob("*.yaml"))


def load_config(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"unknown config '{name}'")
    data = yaml.safe_load(path.read_text()) or {}
    data["name"] = data.get("name") or name
    data["_file"] = str(path)
    return data


def save_config(name: str, data: dict[str, Any]) -> dict[str, Any]:
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"unknown config '{name}'")
    payload = {key: value for key, value in data.items() if not str(key).startswith("_")}
    payload["name"] = name
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return load_config(name)


def flag(cfg: dict[str, Any], name: str) -> bool:
    return bool((cfg.get("features") or {}).get(name))


def load_benchmark_tasks() -> list[dict[str, Any]]:
    tasks = []
    for path in sorted(BENCHMARK_TASKS.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        data["_file"] = str(path)
        tasks.append(data)
    return tasks
