"""Skills, MCP servers, and the tool list handed to the model."""

from __future__ import annotations

import json
import os
import re
import select
import shlex
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from forge.db import Database
from forge.core.context import resolve_policy
from forge.settings import BACKEND_DIR, load_config
from forge.util import new_id, utc_now

BUILTIN: list[dict[str, Any]] = [
    {"name": "search", "group": "Workspace", "summary": "Find text under the run workspace."},
    {"name": "list_dir", "group": "Workspace", "summary": "List a directory inside the workspace."},
    {"name": "read_file", "group": "Workspace", "summary": "Read a file before rewriting it."},
    {"name": "write_file", "group": "Workspace", "summary": "Replace a file with the full new contents."},
    {"name": "terminal", "group": "Workspace", "summary": "Run an allowlisted command such as pytest."},
    {"name": "git", "group": "Workspace", "summary": "Inspect status, diff, or recent commits."},
    {"name": "kg_query", "group": "Graph", "summary": "Ask the knowledge graph for a symbol or task."},
    {
        "name": "read_spill",
        "group": "Context",
        "summary": "Page a spilled tool result by id. Offered when spill is on.",
        "spill": True,
    },
    {
        "name": "finish",
        "group": "Control",
        "summary": "End the task with a short summary. Always offered.",
        "always": True,
    },
]

SEED_SKILLS: list[tuple[str, str, str]] = [
    (
        "plan_the_edit",
        "Settle the files before writing.",
        "Name the files this task should change, then open them, before you write a replacement.",
    ),
    (
        "read_before_rewrite",
        "Keep the current file in view.",
        "Call read_file on a path before write_file so existing functions stay unless the task asks for a change.",
    ),
    (
        "narrow_diff",
        "Touch only the requested behavior.",
        "Prefer a small edit. Leave unrelated modules alone.",
    ),
]

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,40}$")
_PROMPT = re.compile(r"^[a-z_]{1,48}$")
DEMO_NAME = "local-demo"


class StudioError(ValueError):
    pass


class NotFound(StudioError):
    pass


def ensure_seed(db: Database) -> None:
    if db.list_skills():
        return
    now = utc_now()
    for name, description, body in SEED_SKILLS:
        db.insert_skill(
            {
                "id": new_id("skill"),
                "name": name,
                "description": description,
                "body": body,
                "enabled": True,
                "created_at": now,
            }
        )


def _clean_name(value: str, label: str) -> str:
    name = (value or "").strip()
    if not _NAME.match(name):
        raise StudioError(f"{label} must start with a letter and use letters, numbers, _ or -")
    return name


def _prompt_name(server: str, tool: str, used: set[str]) -> str:
    raw = f"{server}_{tool}".lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")[:48]
    if not slug or not _PROMPT.match(slug):
        slug = "mcp_tool"
    reserved = {item["name"] for item in BUILTIN}
    candidate = slug
    if candidate in reserved or candidate in used:
        candidate = f"{slug}_mcp"[:48]
    n = 2
    while candidate in used or candidate in reserved:
        suffix = f"_{n}"
        candidate = f"{slug[: 48 - len(suffix)]}{suffix}"
        n += 1
    used.add(candidate)
    return candidate


def snapshot(db: Database, config_name: str = "full_forge") -> dict[str, Any]:
    ensure_seed(db)
    try:
        cfg = load_config(config_name)
    except FileNotFoundError as exc:
        raise NotFound(str(exc)) from exc
    enabled = set((cfg.get("tools") or {}).get("enabled") or [])
    spill_on = bool(resolve_policy(cfg).get("spill"))
    builtin = []
    for item in BUILTIN:
        if item.get("spill") and not spill_on:
            continue
        builtin.append(
            {
                **item,
                "always": bool(item.get("always") or item.get("spill")),
                "enabled": True if item.get("always") or item.get("spill") else item["name"] in enabled,
            }
        )
    skills = db.list_skills()
    servers = db.list_mcp_servers()
    mcp_tools = _prompt_tools(servers)
    builtin_on = sum(1 for item in builtin if item["enabled"] and not item["always"])
    summary = {
        "builtin_enabled": builtin_on,
        "finish": 1,
        "mcp_tools": len(mcp_tools),
        "skills_enabled": sum(1 for skill in skills if skill["enabled"]),
        "tools_in_prompt": builtin_on + 1 + (1 if spill_on else 0) + len(mcp_tools),
    }
    return {
        "config": cfg.get("name") or config_name,
        "builtin": builtin,
        "skills": skills,
        "mcp": servers,
        "prompt_tools": [item["name"] for item in builtin if item["enabled"]] + [item["prompt_name"] for item in mcp_tools],
        "summary": summary,
    }


def _prompt_tools(servers: list[dict[str, Any]]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    used: set[str] = set()
    for server in servers:
        if not server.get("enabled") or server.get("status") != "connected":
            continue
        for tool in server.get("tools") or []:
            prompt_name = str(tool.get("prompt_name") or "")
            if not _PROMPT.match(prompt_name) or prompt_name in used:
                continue
            used.add(prompt_name)
            found.append(
                {
                    "prompt_name": prompt_name,
                    "name": str(tool.get("name") or prompt_name),
                    "server": server["name"],
                    "description": str(tool.get("description") or ""),
                }
            )
    return found


def load_prompt_extras(db: Database) -> tuple[str, list[str]]:
    """Skill block and MCP tool names that are safe to append to the execute prompt."""
    ensure_seed(db)
    lines = []
    for skill in db.list_skills():
        if not skill.get("enabled"):
            continue
        text = " ".join(str(skill.get("body") or "").split())
        if text:
            lines.append(f"- {skill['name']}: {text}")
    block = ""
    if lines:
        block = ("SKILLS:\n" + "\n".join(lines))[:2000]
    names = [item["prompt_name"] for item in _prompt_tools(db.list_mcp_servers())]
    return block, names


def create_skill(db: Database, *, name: str, description: str = "", body: str = "", enabled: bool = True) -> dict[str, Any]:
    ensure_seed(db)
    clean = _clean_name(name, "skill name")
    if any(skill["name"] == clean for skill in db.list_skills()):
        raise StudioError(f"skill {clean} already exists")
    row = {
        "id": new_id("skill"),
        "name": clean,
        "description": (description or "").strip()[:200],
        "body": (body or "").strip()[:1200],
        "enabled": bool(enabled),
        "created_at": utc_now(),
    }
    if not row["body"]:
        raise StudioError("skill body is required")
    db.insert_skill(row)
    created = db.get_skill(row["id"])
    if not created:
        raise StudioError("could not save skill")
    return created


def update_skill(db: Database, skill_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    current = db.get_skill(skill_id)
    if not current:
        raise NotFound("skill not found")
    payload: dict[str, Any] = {}
    if "name" in fields and fields["name"] is not None:
        payload["name"] = _clean_name(str(fields["name"]), "skill name")
    if "description" in fields and fields["description"] is not None:
        payload["description"] = str(fields["description"]).strip()[:200]
    if "body" in fields and fields["body"] is not None:
        payload["body"] = str(fields["body"]).strip()[:1200]
        if not payload["body"]:
            raise StudioError("skill body is required")
    if "enabled" in fields and fields["enabled"] is not None:
        payload["enabled"] = bool(fields["enabled"])
    if payload:
        db.update_skill(skill_id, **payload)
    updated = db.get_skill(skill_id)
    if not updated:
        raise NotFound("skill not found")
    return updated


def delete_skill(db: Database, skill_id: str) -> None:
    if not db.get_skill(skill_id):
        raise NotFound("skill not found")
    db.delete_skill(skill_id)


def create_mcp(
    db: Database,
    *,
    name: str,
    transport: str,
    command: str = "",
    args: list[str] | None = None,
    url: str = "",
    enabled: bool = False,
) -> dict[str, Any]:
    clean = _clean_name(name, "server name")
    kind = _transport(transport)
    if any(server["name"] == clean for server in db.list_mcp_servers()):
        raise StudioError(f"server {clean} already exists")
    _validate_endpoint(kind, command, url)
    row = {
        "id": new_id("mcp"),
        "name": clean,
        "transport": kind,
        "command": (command or "").strip(),
        "args": list(args or []),
        "url": (url or "").strip(),
        "enabled": bool(enabled),
        "status": "pending" if enabled else "disabled",
        "tools": [],
        "error": "",
        "created_at": utc_now(),
    }
    db.insert_mcp_server(row)
    created = db.get_mcp_server(row["id"])
    if not created:
        raise StudioError("could not save server")
    return created


def update_mcp(db: Database, server_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    current = db.get_mcp_server(server_id)
    if not current:
        raise NotFound("server not found")
    payload: dict[str, Any] = {}
    endpoint_changed = False
    if "name" in fields and fields["name"] is not None:
        payload["name"] = _clean_name(str(fields["name"]), "server name")
    if "transport" in fields and fields["transport"] is not None:
        payload["transport"] = _transport(str(fields["transport"]))
        endpoint_changed = True
    if "command" in fields and fields["command"] is not None:
        payload["command"] = str(fields["command"]).strip()
        endpoint_changed = True
    if "args" in fields and fields["args"] is not None:
        payload["args"] = [str(item) for item in fields["args"]]
        endpoint_changed = True
    if "url" in fields and fields["url"] is not None:
        payload["url"] = str(fields["url"]).strip()
        endpoint_changed = True
    if "enabled" in fields and fields["enabled"] is not None:
        enabled = bool(fields["enabled"])
        payload["enabled"] = enabled
        if not enabled:
            payload["status"] = "disabled"
        elif current.get("tools"):
            payload["status"] = "connected"
            payload["error"] = ""
        else:
            payload["status"] = "pending"
    if endpoint_changed:
        kind = payload.get("transport") or current["transport"]
        command = payload["command"] if "command" in payload else current["command"]
        url = payload["url"] if "url" in payload else current["url"]
        _validate_endpoint(kind, command, url)
        payload["tools"] = []
        payload["error"] = ""
        payload["status"] = "pending" if (payload.get("enabled", current["enabled"])) else "disabled"
    if payload:
        db.update_mcp_server(server_id, **payload)
    updated = db.get_mcp_server(server_id)
    if not updated:
        raise NotFound("server not found")
    return updated


def delete_mcp(db: Database, server_id: str) -> None:
    if not db.get_mcp_server(server_id):
        raise NotFound("server not found")
    db.delete_mcp_server(server_id)


def install_demo(db: Database) -> dict[str, Any]:
    existing = next((server for server in db.list_mcp_servers() if server["name"] == DEMO_NAME), None)
    if existing is None:
        existing = create_mcp(
            db,
            name=DEMO_NAME,
            transport="stdio",
            command=sys.executable,
            args=["-m", "forge.mcp_demo"],
            enabled=True,
        )
    else:
        existing = update_mcp(
            db,
            existing["id"],
            {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "forge.mcp_demo"],
                "url": "",
                "enabled": True,
            },
        )
    return probe_mcp(db, existing["id"])


def probe_mcp(db: Database, server_id: str) -> dict[str, Any]:
    server = db.get_mcp_server(server_id)
    if not server:
        raise NotFound("server not found")
    try:
        discovered = discover_tools(server)
        used: set[str] = set()
        tools = []
        for item in discovered:
            tool_name = str(item.get("name") or "").strip()
            if not tool_name:
                continue
            tools.append(
                {
                    "name": tool_name,
                    "description": str(item.get("description") or "")[:300],
                    "prompt_name": _prompt_name(server["name"], tool_name, used),
                }
            )
        if not tools:
            raise StudioError("server returned no tools")
        db.update_mcp_server(server_id, status="connected", tools=tools, error="", enabled=True)
    except (StudioError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        db.update_mcp_server(server_id, status="failed", tools=[], error=str(exc)[:500])
    updated = db.get_mcp_server(server_id)
    if not updated:
        raise NotFound("server not found")
    return updated


def discover_tools(server: dict[str, Any]) -> list[dict[str, Any]]:
    kind = server.get("transport")
    if kind == "stdio":
        replies = stdio_session(server, ["initialize", "notifications/initialized", "tools/list"])
    elif kind == "http":
        replies = http_session(server["url"], ["initialize", "notifications/initialized", "tools/list"])
    else:
        raise StudioError(f"unsupported transport {kind}")
    listing = next((item for item in replies if item.get("method") == "tools/list"), None)
    if not listing:
        raise StudioError("server did not answer tools/list")
    result = listing.get("result") if isinstance(listing.get("result"), dict) else {}
    tools = result.get("tools") if isinstance(result.get("tools"), list) else []
    return [item for item in tools if isinstance(item, dict)]


def call_mcp_tool(db: Database, prompt_name: str, args: dict[str, Any]) -> tuple[bool, str]:
    servers = db.list_mcp_servers()
    match: tuple[dict[str, Any], dict[str, Any]] | None = None
    for server in servers:
        if not server.get("enabled") or server.get("status") != "connected":
            continue
        for tool in server.get("tools") or []:
            if tool.get("prompt_name") == prompt_name:
                match = (server, tool)
                break
    if match is None:
        return False, f"mcp tool {prompt_name} is not connected"
    server, tool = match
    try:
        if server["transport"] == "stdio":
            replies = stdio_session(
                server,
                ["initialize", "notifications/initialized", "tools/call"],
                call={"name": tool["name"], "arguments": args or {}},
            )
        else:
            replies = http_session(
                server["url"],
                ["initialize", "notifications/initialized", "tools/call"],
                call={"name": tool["name"], "arguments": args or {}},
            )
    except (StudioError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return False, f"mcp error: {exc}"
    reply = next((item for item in replies if item.get("method") == "tools/call"), None)
    if not reply:
        return False, "mcp server returned no result"
    if reply.get("error"):
        return False, f"mcp error: {reply['error']}"
    return True, _result_text(reply.get("result"))[:4000]


def _result_text(result: Any) -> str:
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "\n".join(parts)
        if result.get("text"):
            return str(result["text"])
    return json.dumps(result) if result is not None else ""


def _transport(value: str) -> str:
    kind = (value or "").strip().lower()
    if kind not in {"stdio", "http"}:
        raise StudioError("transport must be stdio or http")
    return kind


def _validate_endpoint(kind: str, command: str, url: str) -> None:
    if kind == "stdio":
        if not (command or "").strip():
            raise StudioError("command is required for stdio")
        if any(char in command for char in "\n\r"):
            raise StudioError("command must be a single executable")
        return
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise StudioError("url must start with http:// or https://")


def _argv(server: dict[str, Any]) -> list[str]:
    command = str(server.get("command") or "").strip()
    raw_args = server.get("args") or []
    if isinstance(raw_args, str):
        args = shlex.split(raw_args)
    else:
        args = [str(item) for item in raw_args if str(item).strip()]
    if not command:
        raise StudioError("command is required for stdio")
    return [command, *args]


def stdio_session(server: dict[str, Any], methods: list[str], call: dict[str, Any] | None = None, timeout: float = 8) -> list[dict[str, Any]]:
    argv = _argv(server)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(BACKEND_DIR),
        env=env,
        bufsize=0,
    )
    replies: list[dict[str, Any]] = []
    try:
        assert proc.stdin is not None and proc.stdout is not None
        next_id = 1
        for method in methods:
            if method.startswith("notifications/"):
                _write_frame(proc.stdin, {"jsonrpc": "2.0", "method": method})
                continue
            params: dict[str, Any]
            if method == "initialize":
                params = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "forge", "version": "0.1.0"},
                }
            elif method == "tools/call":
                params = call or {}
            else:
                params = {}
            _write_frame(proc.stdin, {"jsonrpc": "2.0", "id": next_id, "method": method, "params": params})
            message = _read_frame(proc, timeout)
            message["method"] = method
            if message.get("error"):
                detail = message["error"]
                text = detail.get("message") if isinstance(detail, dict) else str(detail)
                raise StudioError(text or "mcp request failed")
            replies.append(message)
            next_id += 1
        return replies
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def http_session(url: str, methods: list[str], call: dict[str, Any] | None = None, timeout: float = 8) -> list[dict[str, Any]]:
    replies: list[dict[str, Any]] = []
    next_id = 1
    with httpx.Client(timeout=timeout) as client:
        for method in methods:
            if method.startswith("notifications/"):
                client.post(url, json={"jsonrpc": "2.0", "method": method})
                continue
            if method == "initialize":
                params = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "forge", "version": "0.1.0"},
                }
            elif method == "tools/call":
                params = call or {}
            else:
                params = {}
            response = client.post(
                url,
                json={"jsonrpc": "2.0", "id": next_id, "method": method, "params": params},
            )
            response.raise_for_status()
            message = response.json()
            if not isinstance(message, dict):
                raise StudioError("mcp http response was not an object")
            message["method"] = method
            if message.get("error"):
                detail = message["error"]
                text = detail.get("message") if isinstance(detail, dict) else str(detail)
                raise StudioError(text or "mcp request failed")
            replies.append(message)
            next_id += 1
    return replies


def _write_frame(stream, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload).encode()
    stream.write(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
    stream.flush()


def _read_frame(proc: subprocess.Popen, timeout: float) -> dict[str, Any]:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    buf = b""
    while True:
        message, buf = _pop_frame(buf)
        if message is not None:
            return message
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            err = _stderr(proc)
            raise TimeoutError(f"mcp read timed out{err}")
        ready, _, _ = select.select([proc.stdout], [], [], remaining)
        if not ready:
            err = _stderr(proc)
            raise TimeoutError(f"mcp read timed out{err}")
        chunk = os.read(proc.stdout.fileno(), 4096)
        if not chunk:
            err = _stderr(proc)
            raise StudioError(f"mcp server closed the pipe{err}")
        buf += chunk


def _pop_frame(buf: bytes) -> tuple[dict[str, Any] | None, bytes]:
    while True:
        candidates = []
        for sep in (b"\r\n\r\n", b"\n\n"):
            idx = buf.find(sep)
            if idx >= 0:
                candidates.append((idx, sep))
        if not candidates:
            return None, buf
        idx, sep = min(candidates)
        header = buf[:idx].decode("utf-8", "replace")
        match = re.search(r"Content-Length:\s*(\d+)", header, flags=re.IGNORECASE)
        start = idx + len(sep)
        if not match:
            buf = buf[start:]
            continue
        length = int(match.group(1))
        if len(buf) < start + length:
            return None, buf
        body = buf[start : start + length]
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise StudioError(f"mcp returned invalid json: {exc}") from exc
        if not isinstance(payload, dict):
            raise StudioError("mcp frame was not an object")
        return payload, buf[start + length :]


def _stderr(proc: subprocess.Popen) -> str:
    if proc.stderr is None:
        return ""
    try:
        ready, _, _ = select.select([proc.stderr], [], [], 0)
    except (ValueError, OSError):
        return ""
    if not ready:
        return ""
    chunk = os.read(proc.stderr.fileno(), 400)
    text = chunk.decode("utf-8", "replace").strip()
    return f" ({text})" if text else ""
