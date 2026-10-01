"""Multi-level verification funnel.

Order: syntax → unit → integration → requirement → regression → security.
A failure is diagnosed so recovery can classify it.
"""

from __future__ import annotations

import py_compile
import re
import subprocess
from pathlib import Path
from typing import Any

from forge.core.recovery import classify_failure
from forge.core.sandbox import SandboxError, current_runner, pytest_args
from forge.util import extract_json

DIAGNOSE_SYSTEM = """PHASE: DIAGNOSE
You classify a failed software-engineering check.
Return ONLY JSON:
{
  "failure_class": "code_bug" | "env_issue" | "wrong_assumption",
  "evidence": "short quote from the output",
  "why": "one sentence",
  "suggested_strategy": "retry" | "replan" | "rollback" | "isolate" | "ask_human",
  "risk": 0.0
}
failure_class must be exactly one of code_bug, env_issue, wrong_assumption.
risk is your confidence that a human should take over, from 0 to 1.
"""

SECRET_RE = re.compile(
    r"(?i)(api_key|password|secret|token)\s*=\s*['\"][^'\"]{6,}['\"]"
)
SECURITY_RES = [
    (re.compile(r"\beval\s*\("), "eval()"),
    (re.compile(r"\bexec\s*\("), "exec()"),
    (re.compile(r"shell\s*=\s*True"), "shell=True"),
    (SECRET_RE, "hardcoded secret"),
]


def _pytest(workspace: Path, extra: list[str]) -> tuple[bool, str]:
    try:
        proc = current_runner().run(pytest_args(workspace, extra), cwd=workspace, timeout=90)
    except (SandboxError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode == 0, output[-4000:]


def check_syntax(workspace: Path, changed: list[str]) -> tuple[bool, str]:
    files = [workspace / rel for rel in changed if rel.endswith(".py")]
    if not files:
        files = [
            path
            for path in workspace.rglob("*.py")
            if not any(part in {".git", "__pycache__", ".venv"} for part in path.parts)
        ]
    errors = []
    for path in files:
        if not path.exists():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(str(exc))
    if errors:
        return False, "\n".join(errors)[:2000]
    return True, f"compiled {len(files)} python files"


def check_unit(workspace: Path) -> tuple[bool, str]:
    tests = workspace / "tests"
    if not tests.exists():
        return True, "no tests directory; unit level skipped"
    return _pytest(workspace, ["tests"])


def check_integration(workspace: Path) -> tuple[bool, str]:
    if not (workspace / "todo" / "store.py").exists():
        return True, "no todo package; integration smoke skipped"
    try:
        proc = current_runner().run(
            [__import__("sys").executable, "-c", "from todo.store import TodoStore; TodoStore().add('smoke')"],
            cwd=workspace,
            timeout=20,
        )
    except (SandboxError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return False, output[:2000] or f"import smoke failed ({proc.returncode})"
    return True, "imported TodoStore and added a todo"


def check_requirement(workspace: Path, expected: str) -> tuple[bool, str]:
    if not expected.strip():
        return True, "no expected output on this task"
    blob_parts = []
    for path in workspace.rglob("*.py"):
        if any(part in {".git", "__pycache__"} for part in path.parts):
            continue
        blob_parts.append(path.read_text(errors="replace"))
    blob = "\n".join(blob_parts)
    idents = re.findall(r"\b[a-z]+_[a-z0-9_]+\b", expected)
    missing = [ident for ident in idents if ident not in blob]
    if missing:
        return False, f"requirement identifiers missing from the workspace: {', '.join(missing)}"
    return True, "requirement identifiers are present"


def check_regression(workspace: Path, original_tests: list[str]) -> tuple[bool, str]:
    existing = [rel for rel in original_tests if (workspace / rel).exists()]
    if not existing:
        return True, "no original tests to regress"
    ok, output = _pytest(workspace, existing)
    if ok:
        return True, output or "original tests passed"
    return False, output


def check_security(workspace: Path, changed: list[str]) -> tuple[bool, str]:
    files = [workspace / rel for rel in changed if rel.endswith(".py")] or []
    findings = []
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        for pattern, label in SECURITY_RES:
            if pattern.search(text):
                findings.append(f"{path.name}: {label}")
    if findings:
        return False, "; ".join(findings)
    return True, "no security patterns in changed python files"


_LEVELS = {
    "syntax": check_syntax,
    "unit": check_unit,
    "integration": check_integration,
    "requirement": check_requirement,
    "regression": check_regression,
    "security": check_security,
}


async def verify_task(
    *,
    workspace: Path,
    levels: list[str],
    fail_fast: bool,
    expected_output: str,
    changed: list[str],
    original_tests: list[str],
    llm,
    attempt: int,
) -> dict[str, Any]:
    checks = []
    failed = None
    for level in levels:
        if level == "syntax":
            ok, output = check_syntax(workspace, changed)
        elif level == "unit":
            ok, output = check_unit(workspace)
        elif level == "integration":
            ok, output = check_integration(workspace)
        elif level == "requirement":
            ok, output = check_requirement(workspace, expected_output)
        elif level == "regression":
            ok, output = check_regression(workspace, original_tests)
        elif level == "security":
            ok, output = check_security(workspace, changed)
        else:
            ok, output = True, f"unknown level {level} skipped"
        checks.append({"level": level, "ok": ok, "output": output[-1500:]})
        if not ok:
            failed = checks[-1]
            if fail_fast:
                break
    report: dict[str, Any] = {
        "ok": failed is None,
        "checks": checks,
        "diagnosis": None,
    }
    if failed is not None:
        report["diagnosis"] = await diagnose(failed, llm, attempt)
    return report


async def diagnose(failed: dict[str, Any], llm, attempt: int) -> dict[str, Any]:
    user = (
        f"ATTEMPT: {attempt}\n"
        f"LEVEL: {failed['level']}\n"
        f"OUTPUT:\n{failed['output']}"
    )
    try:
        response = await llm.complete(
            [
                {"role": "system", "content": DIAGNOSE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=600,
            json_mode=True,
        )
        data = extract_json(response.text)
        failure_class = data.get("failure_class")
        if failure_class not in {"code_bug", "env_issue", "wrong_assumption"}:
            raise ValueError("bad class")
        data["risk"] = float(data.get("risk") or 0.4)
        data["llm"] = {
            "provider": response.provider,
            "model": response.model,
            "tokens_in": response.prompt_tokens,
            "tokens_out": response.completion_tokens,
            "latency_ms": int(response.latency_ms),
            "cache_read_tokens": response.cache_read_tokens,
            "cache_write_tokens": response.cache_write_tokens,
            "prompt_preview": user[:800],
            "response_preview": response.text[:1200],
        }
        return data
    except Exception:
        fallback = classify_failure(failed["output"], attempt)
        fallback["llm"] = None
        return fallback
