"""Git snapshots around each task: snapshot, keep, or roll back."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(workspace: Path, *args: str) -> str:
    cmd = [
        "git",
        "-c",
        "user.email=forge@local",
        "-c",
        "user.name=FORGE",
        *args,
    ]
    proc = subprocess.run(
        cmd,
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout or "git failed").strip())
    return (proc.stdout or "").strip()


def _add_all(workspace: Path) -> None:
    _run(
        workspace,
        "add",
        "-A",
        "--",
        ".",
        ":(exclude)**/__pycache__/**",
        ":(exclude)**/*.pyc",
        ":(exclude).pytest_cache/**",
    )


def ensure_repo(workspace: Path) -> None:
    if not (workspace / ".git").exists():
        _run(workspace, "init")
        _add_all(workspace)
        _run(workspace, "commit", "-m", "forge: initial snapshot", "--allow-empty")


def start_branch(workspace: Path, run_id: str, base: str | None = None) -> str:
    ensure_repo(workspace)
    branch = f"forge/run-{run_id}"
    if base:
        _run(workspace, "checkout", "-f", "-B", branch, base)
    else:
        _remember_user_head(workspace)
        _run(workspace, "checkout", "-B", branch)
    return branch


def _remember_user_head(workspace: Path) -> None:
    try:
        name = _run(workspace, "rev-parse", "--abbrev-ref", "HEAD")
    except GitError:
        return
    if name.startswith("forge/"):
        return
    try:
        revision = _run(workspace, "rev-parse", "HEAD")
        _run(workspace, "tag", "-f", "forge-user", revision)
    except GitError:
        pass


def user_base(workspace: Path) -> str:
    ensure_repo(workspace)
    try:
        return _run(workspace, "rev-parse", "forge-user")
    except GitError:
        _remember_user_head(workspace)
        return _run(workspace, "rev-parse", "HEAD")


def snapshot(workspace: Path, label: str) -> str:
    ensure_repo(workspace)
    _add_all(workspace)
    _run(workspace, "commit", "-m", f"forge checkpoint: {label}", "--allow-empty")
    return _run(workspace, "rev-parse", "HEAD")


def commit_success(workspace: Path, message: str) -> str:
    _add_all(workspace)
    _run(workspace, "commit", "-m", message, "--allow-empty")
    return _run(workspace, "rev-parse", "HEAD")


def commit_if_dirty(workspace: Path, message: str) -> str | None:
    try:
        status = _run(workspace, "status", "--porcelain")
    except GitError:
        return None
    if not status.strip():
        return None
    return commit_success(workspace, message)


def rollback(workspace: Path, revision: str) -> None:
    _run(workspace, "reset", "--hard", revision)


def unified_diff(workspace: Path, run_id: str = "", limit: int = 120_000) -> dict[str, object]:
    """Working tree compared with the tag written at the start of the run."""
    if not (workspace / ".git").exists():
        return {"files": [], "patch": "", "stat": "", "error": "this folder is not a git repository"}
    base = f"forge-base-{run_id}" if run_id else "forge-base"
    try:
        _run(workspace, "rev-parse", base)
    except GitError:
        base = "forge-base"
    try:
        stat = _run(workspace, "diff", "--stat", base)
        names = _run(workspace, "diff", "--name-status", base)
        patch = _run(workspace, "diff", base)
    except GitError as exc:
        return {"files": [], "patch": "", "stat": "", "error": str(exc)}
    files: list[dict[str, str]] = []
    for line in names.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append({"status": parts[0], "path": parts[-1]})
    untracked = _untracked(workspace)
    extra = []
    for relative in untracked:
        path = workspace / relative
        if not path.is_file():
            continue
        files.append({"status": "A", "path": relative})
        text = path.read_text(errors="replace")
        if len(text) > 8000:
            text = text[:8000] + "\n… truncated"
        extra.append(f"diff --git a/{relative} b/{relative}\nnew file mode 100644\n--- /dev/null\n+++ b/{relative}\n{text}")
    if extra:
        patch = (patch + "\n" + "\n".join(extra)).strip()
    if len(patch) > limit:
        patch = patch[:limit] + "\n… truncated"
    return {"stat": stat, "files": files, "patch": patch}


def _untracked(workspace: Path) -> list[str]:
    try:
        raw = _run(workspace, "ls-files", "--others", "--exclude-standard")
    except GitError:
        return []
    skip = {".git", "__pycache__", ".pytest_cache", ".venv"}
    rows = []
    for line in raw.splitlines():
        relative = line.strip()
        if not relative or any(part in skip for part in Path(relative).parts):
            continue
        rows.append(relative)
    return rows


def diff_stat(workspace: Path, base: str = "HEAD~20") -> str:
    try:
        return _run(workspace, "diff", "--stat", "forge-base", "HEAD")
    except GitError:
        try:
            return _run(workspace, "log", "--oneline", "-n", "12")
        except GitError:
            return ""


def mark_base(workspace: Path, run_id: str = "") -> str:
    revision = _run(workspace, "rev-parse", "HEAD")
    try:
        _run(workspace, "tag", "-f", "forge-base", revision)
        if run_id:
            _run(workspace, "tag", "-f", f"forge-base-{run_id}", revision)
    except GitError:
        pass
    return revision
