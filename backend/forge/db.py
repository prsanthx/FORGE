"""SQLite persistence for repos, runs, telemetry, and failure memory."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from forge.settings import DB_PATH, ensure_dirs
from forge.util import utc_now


SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    url TEXT,
    token TEXT,
    indexed_at TEXT,
    kg_stats TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    config_name TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    workspace TEXT,
    branch TEXT,
    started_at TEXT,
    ended_at TEXT,
    metrics TEXT,
    error TEXT,
    human_question TEXT,
    plan TEXT,
    llm_override TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_key TEXT NOT NULL,
    title TEXT,
    description TEXT,
    dependencies TEXT,
    expected_output TEXT,
    failure_conditions TEXT,
    phase TEXT,
    status TEXT,
    attempt INTEGER DEFAULT 0,
    started_at TEXT,
    ended_at TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    elapsed_ms INTEGER DEFAULT 0,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT,
    provider TEXT,
    model TEXT,
    phase TEXT,
    prompt_preview TEXT,
    response_preview TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_ms INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT,
    name TEXT,
    args TEXT,
    result_preview TEXT,
    ok INTEGER,
    elapsed_ms INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    kind TEXT,
    payload TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS failures (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    repo_id TEXT,
    task_key TEXT,
    failure_class TEXT,
    evidence TEXT,
    strategy TEXT,
    attempt INTEGER,
    resolved INTEGER DEFAULT 0,
    risk REAL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    repo_id TEXT,
    status TEXT,
    created_at TEXT,
    ended_at TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS benchmark_cells (
    id TEXT PRIMARY KEY,
    benchmark_id TEXT NOT NULL,
    config_name TEXT,
    task_id TEXT,
    difficulty TEXT,
    run_id TEXT,
    metrics TEXT
);
CREATE TABLE IF NOT EXISTS kg_nodes (
    repo_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    kind TEXT,
    name TEXT,
    qualname TEXT,
    file TEXT,
    line INTEGER,
    signature TEXT,
    doc TEXT,
    snippet TEXT,
    PRIMARY KEY (repo_id, node_id)
);
CREATE TABLE IF NOT EXISTS kg_edges (
    repo_id TEXT NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    rel TEXT NOT NULL,
    PRIMARY KEY (repo_id, src, dst, rel)
);
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    body TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    transport TEXT NOT NULL,
    command TEXT,
    args TEXT,
    url TEXT,
    enabled INTEGER DEFAULT 0,
    status TEXT,
    tools TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
"""


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class Database:
    def __init__(self, path=DB_PATH):
        ensure_dirs()
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # --- repos ---
    def insert_repo(self, repo: dict[str, Any]) -> None:
        self.execute(
            """INSERT INTO repos (id, name, source, path, url, token, indexed_at, kg_stats, created_at)
               VALUES (:id, :name, :source, :path, :url, :token, :indexed_at, :kg_stats, :created_at)""",
            repo,
        )

    def list_repos(self) -> list[dict[str, Any]]:
        return [self._public_repo(row) for row in self.query("SELECT * FROM repos ORDER BY created_at DESC")]

    def get_repo(self, repo_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM repos WHERE id = ?", (repo_id,))
        return self._public_repo(row) if row else None

    def get_repo_raw(self, repo_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM repos WHERE id = ?", (repo_id,))

    def update_repo_index(self, repo_id: str, stats: dict[str, Any]) -> None:
        self.execute(
            "UPDATE repos SET indexed_at = ?, kg_stats = ? WHERE id = ?",
            (utc_now(), json.dumps(stats), repo_id),
        )

    def _public_repo(self, row: dict[str, Any]) -> dict[str, Any]:
        stats = _loads(row.get("kg_stats"), {})
        return {
            "id": row["id"],
            "name": row["name"],
            "source": row["source"],
            "path": row["path"],
            "url": row.get("url"),
            "token_set": bool(row.get("token")),
            "indexed_at": row.get("indexed_at"),
            "kg_stats": stats,
            "created_at": row["created_at"],
        }

    # --- runs ---
    def insert_run(self, run: dict[str, Any]) -> None:
        payload = dict(run)
        payload["metrics"] = json.dumps(payload.get("metrics") or {})
        payload["plan"] = json.dumps(payload.get("plan") or {})
        payload["llm_override"] = json.dumps(payload.get("llm_override") or {})
        self.execute(
            """INSERT INTO runs (id, repo_id, config_name, goal, status, workspace, branch,
                   started_at, ended_at, metrics, error, human_question, plan, llm_override)
               VALUES (:id, :repo_id, :config_name, :goal, :status, :workspace, :branch,
                   :started_at, :ended_at, :metrics, :error, :human_question, :plan, :llm_override)""",
            payload,
        )

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        for key in ("metrics", "plan", "llm_override"):
            if key in fields and not isinstance(fields[key], str):
                fields[key] = json.dumps(fields[key])
        cols = ", ".join(f"{key} = ?" for key in fields)
        self.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))

    def list_runs(self) -> list[dict[str, Any]]:
        return [self._public_run(row) for row in self.query("SELECT * FROM runs ORDER BY started_at DESC")]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM runs WHERE id = ?", (run_id,))
        if not row:
            return None
        run = self._public_run(row)
        run["tasks"] = self.tasks_for(run_id)
        run["llm_calls"] = self.query(
            "SELECT * FROM llm_calls WHERE run_id = ? ORDER BY created_at", (run_id,)
        )
        run["tool_calls"] = self.query(
            "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY created_at", (run_id,)
        )
        run["failures"] = self.query(
            "SELECT * FROM failures WHERE run_id = ? ORDER BY created_at", (run_id,)
        )
        return run

    def _public_run(self, row: dict[str, Any]) -> dict[str, Any]:
        llm = _loads(row.get("llm_override"), {})
        if isinstance(llm, dict) and llm.get("api_key"):
            llm = {key: value for key, value in llm.items() if key != "api_key"}
            llm["api_key_set"] = True
        return {
            "id": row["id"],
            "repo_id": row["repo_id"],
            "config_name": row["config_name"],
            "goal": row["goal"],
            "status": row["status"],
            "workspace": row.get("workspace"),
            "branch": row.get("branch"),
            "started_at": row.get("started_at"),
            "ended_at": row.get("ended_at"),
            "metrics": _loads(row.get("metrics"), {}),
            "error": row.get("error"),
            "human_question": row.get("human_question"),
            "plan": _loads(row.get("plan"), {}),
            "llm": llm,
        }

    def replace_tasks(self, run_id: str, tasks: list[dict[str, Any]]) -> None:
        self.execute("DELETE FROM tasks WHERE run_id = ?", (run_id,))
        for task in tasks:
            self.insert_task(task)

    def insert_task(self, task: dict[str, Any]) -> None:
        payload = dict(task)
        payload["dependencies"] = json.dumps(payload.get("dependencies") or [])
        payload["failure_conditions"] = json.dumps(payload.get("failure_conditions") or [])
        self.execute(
            """INSERT INTO tasks (id, run_id, task_key, title, description, dependencies,
                   expected_output, failure_conditions, phase, status, attempt, started_at,
                   ended_at, tokens_in, tokens_out, elapsed_ms, summary)
               VALUES (:id, :run_id, :task_key, :title, :description, :dependencies,
                   :expected_output, :failure_conditions, :phase, :status, :attempt, :started_at,
                   :ended_at, :tokens_in, :tokens_out, :elapsed_ms, :summary)""",
            payload,
        )

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        for key in ("dependencies", "failure_conditions"):
            if key in fields and not isinstance(fields[key], str):
                fields[key] = json.dumps(fields[key])
        cols = ", ".join(f"{key} = ?" for key in fields)
        self.execute(f"UPDATE tasks SET {cols} WHERE id = ?", (*fields.values(), task_id))

    def tasks_for(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM tasks WHERE run_id = ? ORDER BY rowid", (run_id,))
        for row in rows:
            row["dependencies"] = _loads(row.get("dependencies"), [])
            row["failure_conditions"] = _loads(row.get("failure_conditions"), [])
        return rows

    def add_llm_call(self, row: dict[str, Any]) -> None:
        self.execute(
            """INSERT INTO llm_calls (id, run_id, task_id, provider, model, phase, prompt_preview,
                   response_preview, tokens_in, tokens_out, latency_ms, created_at)
               VALUES (:id, :run_id, :task_id, :provider, :model, :phase, :prompt_preview,
                   :response_preview, :tokens_in, :tokens_out, :latency_ms, :created_at)""",
            row,
        )

    def add_tool_call(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        if not isinstance(payload.get("args"), str):
            payload["args"] = json.dumps(payload.get("args") or {})
        self.execute(
            """INSERT INTO tool_calls (id, run_id, task_id, name, args, result_preview, ok, elapsed_ms, created_at)
               VALUES (:id, :run_id, :task_id, :name, :args, :result_preview, :ok, :elapsed_ms, :created_at)""",
            payload,
        )

    def add_event(self, run_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"run_id": run_id, "kind": kind, "payload": payload, "created_at": utc_now()}
        self.execute(
            "INSERT INTO events (run_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (run_id, kind, json.dumps(payload), event["created_at"]),
        )
        event["payload"] = payload
        return event

    def events_for(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT id, kind, payload, created_at FROM events WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        for row in rows:
            row["payload"] = _loads(row.get("payload"), {})
        return rows

    def add_failure(self, row: dict[str, Any]) -> None:
        self.execute(
            """INSERT INTO failures (id, run_id, repo_id, task_key, failure_class, evidence,
                   strategy, attempt, resolved, risk, created_at)
               VALUES (:id, :run_id, :repo_id, :task_key, :failure_class, :evidence,
                   :strategy, :attempt, :resolved, :risk, :created_at)""",
            row,
        )

    def resolve_failures(self, run_id: str, task_key: str) -> None:
        self.execute(
            "UPDATE failures SET resolved = 1 WHERE run_id = ? AND task_key = ? AND resolved = 0",
            (run_id, task_key),
        )

    def recent_failures(self, repo_id: str, limit: int = 6) -> list[dict[str, Any]]:
        return self.query(
            """SELECT failure_class, evidence, strategy, attempt, resolved, created_at, task_key
               FROM failures WHERE repo_id = ? ORDER BY created_at DESC LIMIT ?""",
            (repo_id, limit),
        )

    def insert_benchmark(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["summary"] = json.dumps(payload.get("summary") or {})
        self.execute(
            """INSERT INTO benchmarks (id, repo_id, status, created_at, ended_at, summary)
               VALUES (:id, :repo_id, :status, :created_at, :ended_at, :summary)""",
            payload,
        )

    def update_benchmark(self, bench_id: str, **fields: Any) -> None:
        if "summary" in fields and not isinstance(fields["summary"], str):
            fields["summary"] = json.dumps(fields["summary"])
        cols = ", ".join(f"{key} = ?" for key in fields)
        self.execute(f"UPDATE benchmarks SET {cols} WHERE id = ?", (*fields.values(), bench_id))

    def add_cell(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["metrics"] = json.dumps(payload.get("metrics") or {})
        self.execute(
            """INSERT INTO benchmark_cells (id, benchmark_id, config_name, task_id, difficulty, run_id, metrics)
               VALUES (:id, :benchmark_id, :config_name, :task_id, :difficulty, :run_id, :metrics)""",
            payload,
        )

    def list_benchmarks(self) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM benchmarks ORDER BY created_at DESC")
        for row in rows:
            row["summary"] = _loads(row.get("summary"), {})
        return rows

    def get_benchmark(self, bench_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM benchmarks WHERE id = ?", (bench_id,))
        if not row:
            return None
        row["summary"] = _loads(row.get("summary"), {})
        cells = self.query("SELECT * FROM benchmark_cells WHERE benchmark_id = ?", (bench_id,))
        for cell in cells:
            cell["metrics"] = _loads(cell.get("metrics"), {})
        row["cells"] = cells
        return row

    # --- studio: skills and MCP servers ---
    def list_skills(self) -> list[dict[str, Any]]:
        return [self._public_skill(row) for row in self.query("SELECT * FROM skills ORDER BY created_at ASC")]

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM skills WHERE id = ?", (skill_id,))
        return self._public_skill(row) if row else None

    def insert_skill(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["enabled"] = 1 if payload.get("enabled", True) else 0
        self.execute(
            """INSERT INTO skills (id, name, description, body, enabled, created_at)
               VALUES (:id, :name, :description, :body, :enabled, :created_at)""",
            payload,
        )

    def update_skill(self, skill_id: str, **fields: Any) -> None:
        allowed = {key: value for key, value in fields.items() if key in {"name", "description", "body", "enabled"}}
        if not allowed:
            return
        if "enabled" in allowed:
            allowed["enabled"] = 1 if allowed["enabled"] else 0
        cols = ", ".join(f"{key} = ?" for key in allowed)
        self.execute(f"UPDATE skills SET {cols} WHERE id = ?", (*allowed.values(), skill_id))

    def delete_skill(self, skill_id: str) -> None:
        self.execute("DELETE FROM skills WHERE id = ?", (skill_id,))

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        return [self._public_mcp(row) for row in self.query("SELECT * FROM mcp_servers ORDER BY created_at ASC")]

    def get_mcp_server(self, server_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM mcp_servers WHERE id = ?", (server_id,))
        return self._public_mcp(row) if row else None

    def insert_mcp_server(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["enabled"] = 1 if payload.get("enabled") else 0
        payload["args"] = json.dumps(payload.get("args") or [])
        payload["tools"] = json.dumps(payload.get("tools") or [])
        self.execute(
            """INSERT INTO mcp_servers
               (id, name, transport, command, args, url, enabled, status, tools, error, created_at)
               VALUES (:id, :name, :transport, :command, :args, :url, :enabled, :status, :tools, :error, :created_at)""",
            payload,
        )

    def update_mcp_server(self, server_id: str, **fields: Any) -> None:
        allowed = {
            key: value
            for key, value in fields.items()
            if key in {"name", "transport", "command", "args", "url", "enabled", "status", "tools", "error"}
        }
        if not allowed:
            return
        if "enabled" in allowed:
            allowed["enabled"] = 1 if allowed["enabled"] else 0
        if "args" in allowed and not isinstance(allowed["args"], str):
            allowed["args"] = json.dumps(allowed["args"] or [])
        if "tools" in allowed and not isinstance(allowed["tools"], str):
            allowed["tools"] = json.dumps(allowed["tools"] or [])
        cols = ", ".join(f"{key} = ?" for key in allowed)
        self.execute(f"UPDATE mcp_servers SET {cols} WHERE id = ?", (*allowed.values(), server_id))

    def delete_mcp_server(self, server_id: str) -> None:
        self.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))

    def _public_skill(self, row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["description"] = item.get("description") or ""
        item["body"] = item.get("body") or ""
        return item

    def _public_mcp(self, row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["command"] = item.get("command") or ""
        item["url"] = item.get("url") or ""
        item["status"] = item.get("status") or "pending"
        item["error"] = item.get("error") or ""
        item["args"] = _loads(item.get("args"), [])
        item["tools"] = _loads(item.get("tools"), [])
        if not isinstance(item["args"], list):
            item["args"] = []
        if not isinstance(item["tools"], list):
            item["tools"] = []
        return item
