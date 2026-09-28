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


def ensure_repo(workspace: Path) -> None:
    if not (workspace / ".git").exists():
        _run(workspace, "init")
        _run(workspace, "add", "-A")
        _run(workspace, "commit", "-m", "forge: initial snapshot", "--allow-empty")


def start_branch(workspace: Path, run_id: str) -> str:
    ensure_repo(workspace)
    branch = f"forge/run-{run_id}"
    _run(workspace, "checkout", "-B", branch)
    return branch


def snapshot(workspace: Path, label: str) -> str:
    ensure_repo(workspace)
    _run(workspace, "add", "-A")
    _run(workspace, "commit", "-m", f"forge checkpoint: {label}", "--allow-empty")
    return _run(workspace, "rev-parse", "HEAD")


def commit_success(workspace: Path, message: str) -> str:
    _run(workspace, "add", "-A")
    _run(workspace, "commit", "-m", message, "--allow-empty")
    return _run(workspace, "rev-parse", "HEAD")


def rollback(workspace: Path, revision: str) -> None:
    _run(workspace, "reset", "--hard", revision)


def diff_stat(workspace: Path, base: str = "HEAD~20") -> str:
    try:
        return _run(workspace, "diff", "--stat", "forge-base", "HEAD")
    except GitError:
        try:
            return _run(workspace, "log", "--oneline", "-n", "12")
        except GitError:
            return ""


def mark_base(workspace: Path) -> str:
    revision = _run(workspace, "rev-parse", "HEAD")
    try:
        _run(workspace, "tag", "-f", "forge-base", revision)
    except GitError:
        pass
    return revision
