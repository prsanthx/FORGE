"""Recovery policy and persistent failure memory."""

from forge.benchmark.runner import _glyphs
from forge.core.recovery import classify_failure, decide_strategy
from forge.db import Database


def test_classify_real_outputs():
    assert classify_failure("E   AssertionError: done is False")["failure_class"] == "code_bug"
    assert classify_failure("ModuleNotFoundError: No module named 'nope'")["failure_class"] == "env_issue"
    assert classify_failure("FileNotFoundError: missing todo/store.py")["failure_class"] == "wrong_assumption"


def test_code_bug_retries_then_replans_then_isolates():
    strategies = ["retry", "replan", "rollback", "isolate", "ask_human"]
    first = decide_strategy(
        failure_class="code_bug", risk=0.4, attempt=1, max_retries=2, risk_threshold=0.72, strategies=strategies
    )
    assert first == "retry"
    second = decide_strategy(
        failure_class="code_bug", risk=0.5, attempt=2, max_retries=2, risk_threshold=0.72, strategies=strategies
    )
    assert second == "retry"
    third = decide_strategy(
        failure_class="code_bug", risk=0.5, attempt=3, max_retries=2, risk_threshold=0.72, strategies=strategies
    )
    assert third == "replan"


def test_high_risk_asks_a_human():
    choice = decide_strategy(
        failure_class="code_bug",
        risk=0.91,
        attempt=1,
        max_retries=3,
        risk_threshold=0.72,
        strategies=["retry", "ask_human"],
    )
    assert choice == "ask_human"


def test_env_issue_retries_once_then_asks():
    strategies = ["retry", "ask_human", "isolate"]
    assert (
        decide_strategy(
            failure_class="env_issue", risk=0.4, attempt=1, max_retries=3, risk_threshold=0.9, strategies=strategies
        )
        == "retry"
    )
    assert (
        decide_strategy(
            failure_class="env_issue", risk=0.4, attempt=2, max_retries=3, risk_threshold=0.9, strategies=strategies
        )
        == "ask_human"
    )


def test_wrong_assumption_replans():
    choice = decide_strategy(
        failure_class="wrong_assumption",
        risk=0.4,
        attempt=1,
        max_retries=2,
        risk_threshold=0.8,
        strategies=["retry", "replan", "rollback"],
    )
    assert choice == "replan"


def test_pytest_progress_glyphs_count_when_summary_is_missing():
    passed, failed, errors = _glyphs("....                                                                     [100%]\n")
    assert (passed, failed, errors) == (4, 0, 0)
    assert _glyphs("..F.                                                                     [100%]") == (3, 1, 0)


def test_failure_history_persists(tmp_path):
    db = Database(tmp_path / "mem.db")
    db.insert_repo(
        {
            "id": "repo_1",
            "name": "demo",
            "source": "local",
            "path": str(tmp_path),
            "url": "",
            "token": "",
            "indexed_at": None,
            "kg_stats": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    db.add_failure(
        {
            "id": "fail_1",
            "run_id": "run_1",
            "repo_id": "repo_1",
            "task_key": "t1",
            "failure_class": "code_bug",
            "evidence": "AssertionError",
            "strategy": "retry",
            "attempt": 1,
            "resolved": 0,
            "risk": 0.4,
            "created_at": "2026-01-01T00:00:01+00:00",
        }
    )
    again = Database(tmp_path / "mem.db")
    rows = again.recent_failures("repo_1")
    assert rows[0]["failure_class"] == "code_bug"
    again.resolve_failures("run_1", "t1")
    assert again.recent_failures("repo_1")[0]["resolved"] == 1
