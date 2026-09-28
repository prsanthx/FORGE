"""Verification funnel levels."""

from pathlib import Path

from forge.core.verifier import check_requirement, check_security, check_syntax, verify_task
import asyncio


def test_syntax_fails_on_broken_python(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_text("def nope(:\n")
    ok, output = check_syntax(tmp_path, ["bad.py"])
    assert not ok
    assert "bad.py" in output or "Syntax" in output or "error" in output.lower()


def test_syntax_passes_on_valid_module(tmp_path: Path):
    (tmp_path / "ok.py").write_text("def ok():\n    return 1\n")
    ok, _output = check_syntax(tmp_path, ["ok.py"])
    assert ok


def test_security_flags_eval(tmp_path: Path):
    (tmp_path / "risky.py").write_text("def run(x):\n    return eval(x)\n")
    ok, output = check_security(tmp_path, ["risky.py"])
    assert not ok
    assert "eval" in output


def test_requirement_checklist_looks_for_identifiers(tmp_path: Path):
    (tmp_path / "store.py").write_text("def mark_done():\n    return True\n")
    ok, _output = check_requirement(tmp_path, "mark_done sets done to true")
    assert ok
    missing, output = check_requirement(tmp_path, "call export_csv before returning")
    assert not missing
    assert "export_csv" in output


def test_funnel_stops_at_first_failure(tmp_path: Path):
    (tmp_path / "bad.py").write_text("def nope(:\n")

    class NoLLM:
        async def complete(self, *args, **kwargs):
            raise AssertionError("diagnosis fallback should not need a successful model")

    report = asyncio.run(
        verify_task(
            workspace=tmp_path,
            levels=["syntax", "unit", "security"],
            fail_fast=True,
            expected_output="mark_done",
            changed=["bad.py"],
            original_tests=[],
            llm=NoLLM(),
            attempt=1,
        )
    )
    assert report["ok"] is False
    assert [check["level"] for check in report["checks"]] == ["syntax"]
    assert report["diagnosis"]["failure_class"] in {"code_bug", "env_issue", "wrong_assumption"}
