"""Workspace tools. Paths cannot escape the project, and pip cannot install."""

from __future__ import annotations

import ast
import subprocess
import time
from pathlib import Path
from typing import Any

from forge.core.sandbox import SandboxError, current_runner, split_command
from forge.kg.query import GraphRetriever

ALLOWED_BINARIES = {"python", "python3", "pytest", "git", "ls", "cat"}
GIT_ALLOWED = {"status", "diff", "log", "rev-parse"}


class ToolError(ValueError):
    pass


def resolve_path(root: Path, relative: str) -> Path:
    rel = (relative or ".").strip().lstrip("/")
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ToolError(f"path escapes the workspace: {relative}")
    return candidate


def _symbols(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.append(child.name)
    return names


def tool_search(root: Path, query: str, glob: str = "*.py") -> str:
    needle = (query or "").lower()
    if not needle:
        return "empty query"
    hits = []
    for path in sorted(root.rglob(glob or "*.py")):
        if any(part in {".git", "__pycache__", ".venv"} for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            if needle in line.lower():
                rel = path.relative_to(root)
                hits.append(f"{rel}:{number}: {line.strip()[:200]}")
                if len(hits) >= 30:
                    return "\n".join(hits)
    return "\n".join(hits) or "no matches"


def tool_list_dir(root: Path, relative: str = ".") -> str:
    path = resolve_path(root, relative or ".")
    if not path.exists():
        return f"missing directory: {relative}"
    if path.is_file():
        return str(path.relative_to(root))
    rows = []
    for child in sorted(path.rglob("*")):
        if any(part in {".git", "__pycache__", ".venv", ".pytest_cache"} for part in child.parts):
            continue
        if child.is_file():
            rows.append(str(child.relative_to(root)))
        if len(rows) >= 80:
            break
    return "\n".join(rows) or "(empty)"


def tool_read_file(root: Path, relative: str, start: int | None = None, end: int | None = None) -> str:
    path = resolve_path(root, relative)
    if not path.is_file():
        return f"not a file: {relative}"
    text = path.read_text(errors="replace")
    symbols = ", ".join(_symbols(text)) or "(none)"
    lines = text.splitlines()
    if start or end:
        s = max(1, int(start or 1)) - 1
        e = int(end or len(lines))
        body = "\n".join(lines[s:e])
    else:
        body = text
    return f"path: {relative}\nsymbols: {symbols}\n---\n{body}"


def tool_write_file(root: Path, relative: str, content: str) -> str:
    if not relative or relative.endswith("/"):
        raise ToolError("write_file requires a file path")
    path = resolve_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"wrote {relative} ({len(content.splitlines())} lines)"


def tool_terminal(root: Path, command: str) -> str:
    if any(token in (command or "") for token in (";", "&&", "|", "`", "$(", ">", "<")):
        raise ToolError("shell operators are not allowed")
    try:
        argv = split_command(command)
    except SandboxError as exc:
        raise ToolError(str(exc)) from exc
    if not argv:
        raise ToolError("empty command")
    binary = Path(argv[0]).name
    if binary not in ALLOWED_BINARIES:
        raise ToolError(f"command not allowed: {binary}. Commands stay inside this project, and pip install is blocked.")
    try:
        proc = current_runner().run(argv, cwd=root, timeout=40)
    except SandboxError as exc:
        raise ToolError(str(exc)) from exc
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return f"exit={proc.returncode}\n{output}"


def tool_git(root: Path, args: list[str] | str) -> str:
    if isinstance(args, str):
        try:
            argv = split_command(args)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc
    else:
        argv = list(args)
    if not argv or argv[0] not in GIT_ALLOWED:
        raise ToolError("git tool only allows status, diff, log, rev-parse")
    proc = subprocess.run(
        ["git", *argv],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return f"exit={proc.returncode}\n{output[:3000]}"


def tool_kg_query(retriever: GraphRetriever | None, query: str) -> str:
    if retriever is None:
        return "knowledge graph is not enabled for this run"
    hits = retriever.search(query, limit=6)
    if not hits:
        return "no graph hits"
    rows = []
    for hit in hits:
        rows.append(
            f"{hit.get('kind')} {hit.get('qualname')} @ {hit.get('file')}:{hit.get('line')} :: {hit.get('signature')}"
        )
    return "\n".join(rows)


def execute_tool(
    name: str,
    args: dict,
    *,
    root: Path,
    retriever: GraphRetriever | None = None,
    session: Any | None = None,
) -> tuple[bool, str, int]:
    started = time.perf_counter()
    try:
        if name == "search":
            result = tool_search(root, str(args.get("query") or ""), str(args.get("glob") or "*.py"))
        elif name == "list_dir":
            result = tool_list_dir(root, str(args.get("path") or "."))
        elif name == "read_file":
            result = tool_read_file(
                root,
                str(args.get("path") or ""),
                args.get("start"),
                args.get("end"),
            )
        elif name == "write_file":
            result = tool_write_file(root, str(args.get("path") or ""), str(args.get("content") or ""))
        elif name == "terminal":
            result = tool_terminal(root, str(args.get("command") or ""))
        elif name == "git":
            result = tool_git(root, args.get("args") or args.get("command") or "status")
        elif name == "kg_query":
            result = tool_kg_query(retriever, str(args.get("query") or ""))
        elif name == "read_spill":
            if session is None:
                raise ToolError("read_spill is not active for this run")
            result = session.read_spill(
                str(args.get("id") or args.get("spill") or ""),
                args.get("start"),
                args.get("end"),
            )
        else:
            raise ToolError(f"unknown tool {name}")
        ok = True
    except (ToolError, SandboxError, OSError, subprocess.TimeoutExpired) as exc:
        result = f"tool error: {exc}"
        ok = False
    if session is not None and ok:
        result = session.shape(name, args, result, root=root)
    elif session is not None and name in {"write_file", "terminal"}:
        session.reads.clear()
    elapsed = int((time.perf_counter() - started) * 1000)
    return ok, result, elapsed
