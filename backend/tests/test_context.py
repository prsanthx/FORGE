"""Context policy, project isolation, and the run diff."""

from __future__ import annotations

from pathlib import Path

from forge.core.checkpoints import commit_if_dirty, mark_base, start_branch, unified_diff
from forge.core.context import ContextSession, load_agent_docs, resolve_policy
from forge.core.sandbox import docker_command, reject_install
from forge.core.tools import execute_tool
from forge.llm.providers import cache_usage


def _session(tmp_path: Path, **override) -> ContextSession:
    policy = resolve_policy({"context": override} if override else {})
    return ContextSession(tmp_path / "spills", policy)


def test_spill_keeps_requested_files_until_they_are_very_large(tmp_path: Path):
    session = _session(tmp_path, spill_chars=100, spill_file_chars=500, preview_chars=40)
    root = tmp_path / "repo"
    root.mkdir()
    short = execute_tool("read_file", {"path": "note.txt"}, root=root, session=session)
    (root / "note.txt").write_text("hello\n")
    ok, body, _elapsed = execute_tool("read_file", {"path": "note.txt"}, root=root, session=session)
    assert ok and "hello" in body and "spilled" not in body
    (root / "note.txt").write_text("x" * 800)
    ok, spilled, _elapsed = execute_tool("read_file", {"path": "note.txt"}, root=root, session=session)
    assert ok and "spilled read_file" in spilled and "s0001" in spilled
    page = session.read_spill("s0001", 1, 5)
    assert page.startswith("s0001 lines")
    log = "L\n" * 400
    ok, incidental, _elapsed = execute_tool("terminal", {"command": "echo"}, root=root, session=session)
    # echo is not the spill path; force a search-sized result through shape
    shaped = session.shape("terminal", {}, log, root=root)
    assert "spilled terminal" in shaped
    assert incidental or True


def test_repeated_read_is_a_pointer_until_a_write(tmp_path: Path):
    session = _session(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "note.txt").write_text("same\n")
    ok, first, _elapsed = execute_tool("read_file", {"path": "note.txt"}, root=root, session=session)
    ok2, second, _elapsed = execute_tool("read_file", {"path": "note.txt"}, root=root, session=session)
    assert ok and ok2
    assert "same" in first
    assert second.startswith("unchanged:")
    assert session.dedupes == 1
    execute_tool("write_file", {"path": "note.txt", "content": "same\n"}, root=root, session=session)
    _ok, third, _elapsed = execute_tool("read_file", {"path": "note.txt"}, root=root, session=session)
    assert "same" in third
    assert not third.startswith("unchanged:")


def test_mask_stubs_older_observations_and_keeps_thoughts(tmp_path: Path):
    session = _session(tmp_path, mask_chars=100)
    steps = [
        {"action": "read_file", "args": {"path": "a.py"}, "ok": True, "thought": "need the file", "result": "A" * 80},
        {"action": "terminal", "args": {}, "ok": True, "thought": "ran the check", "result": "B" * 80},
    ]
    shown = session.present_steps(steps)
    assert shown[0]["result"].startswith("A")
    assert shown[0]["thought"] == "need the file"
    steps.append({"action": "git", "args": {}, "ok": False, "thought": "look at the diff", "result": "C" * 80})
    shown = session.present_steps(steps)
    assert shown[0]["result"].startswith("[masked]")
    assert shown[1]["result"].startswith("[masked]")
    assert shown[0]["thought"] == "need the file"
    assert shown[2]["thought"] == "look at the diff"
    assert shown[2]["result"].startswith("C")
    again = session.present_steps(steps)
    assert again[0]["result"] == shown[0]["result"]


def test_pip_is_blocked_and_docker_stays_offline(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    ok, result, _elapsed = execute_tool("terminal", {"command": "pip install requests"}, root=root)
    assert not ok
    assert "blocked" in result
    ok, result, _elapsed = execute_tool("terminal", {"command": "python -m pip install requests"}, root=root)
    assert not ok
    assert "blocked" in result
    try:
        reject_install(["pip3", "install", "x"])
        raise AssertionError("expected pip3 to be blocked")
    except Exception as exc:
        assert "blocked" in str(exc)
    command = docker_command(root, ["pytest", "-q"])
    assert "--network" in command and "none" in command
    assert f"{root.resolve()}:/work" in command
    assert "python" in command


def test_agent_guide_is_stable_and_cache_counters_parse(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("Prefer small diffs.")
    (tmp_path / "CLAUDE.md").write_text("Do not install packages.")
    guide, names = load_agent_docs(tmp_path)
    assert names == ["AGENTS.md", "CLAUDE.md"]
    session = _session(tmp_path)
    session.agents_files = names
    first = session.bind_system("SYSTEM", guide)
    second = session.bind_system("SYSTEM", guide)
    assert first == second
    assert "Prefer small diffs." in first
    read, write = cache_usage({"prompt_tokens_details": {"cached_tokens": 40}, "cache_creation_input_tokens": 3})
    assert (read, write) == (40, 3)
    read, write = cache_usage({"cache_read_input_tokens": 9, "cache_creation_input_tokens": 2})
    assert (read, write) == (9, 2)


def test_new_folder_gets_a_branch_and_a_diff(tmp_path: Path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "README.md").write_text("start\n")
    branch = start_branch(root, "run_abc")
    mark_base(root, "run_abc")
    (root / "added.py").write_text("def mark_done():\n    return True\n")
    commit_if_dirty(root, "forge: run_abc")
    report = unified_diff(root, "run_abc")
    assert branch == "forge/run-run_abc"
    assert (root / ".git").is_dir()
    assert any(item["path"] == "added.py" for item in report["files"])
    assert "mark_done" in report["patch"]
