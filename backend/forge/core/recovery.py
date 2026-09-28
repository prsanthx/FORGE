"""Failure classification and adaptive recovery.

Classes match the product model: Code Bug, Environment Issue, Wrong Assumption.
Strategies: Retry, Replan, Rollback, Isolate, Ask Human.
"""

from __future__ import annotations

from typing import Any


def classify_failure(output: str, attempt: int = 1) -> dict[str, Any]:
    """Deterministic diagnosis used when a model response cannot be parsed,
    and by MockLLM so demo runs still classify real tool and test output.
    """
    text = output or ""
    low = text.lower()
    if any(
        token in low
        for token in (
            "no module named",
            "modulenotfounderror",
            "command not found",
            "permission denied",
            "connection refused",
            "address already in use",
        )
    ):
        failure_class = "env_issue"
        strategy = "retry"
        risk = 0.62
        why = "The failure looks environmental: a missing module, command, permission, or local service."
    elif any(
        token in low
        for token in (
            "wrong file",
            "not in the repository",
            "no such file",
            "filenotfounderror",
            "wrong assumption",
        )
    ):
        failure_class = "wrong_assumption"
        strategy = "replan"
        risk = 0.58
        why = "The edit missed the real file or followed an assumption the repository does not support."
    else:
        failure_class = "code_bug"
        strategy = "retry"
        risk = 0.38
        why = "The failure looks like incorrect program behavior or a broken test assertion."
    risk = round(min(0.95, risk + 0.05 * max(0, attempt - 1)), 2)
    evidence = text.strip()[-1500:]
    return {
        "failure_class": failure_class,
        "evidence": evidence,
        "why": why,
        "suggested_strategy": strategy,
        "risk": risk,
    }


def decide_strategy(
    *,
    failure_class: str,
    risk: float,
    attempt: int,
    max_retries: int,
    risk_threshold: float,
    strategies: list[str],
) -> str:
    """Pick a recovery action. The harness decides; the model only advises."""
    allowed = set(strategies) or {"retry"}

    def pick(*options: str) -> str:
        for option in options:
            if option in allowed:
                return option
        return next(iter(allowed))

    if risk >= risk_threshold:
        return pick("ask_human", "isolate", "rollback", "replan", "retry")

    if failure_class == "env_issue":
        if attempt <= 1:
            return pick("retry", "ask_human", "isolate")
        return pick("ask_human", "isolate", "retry")

    if failure_class == "wrong_assumption":
        if attempt <= max(1, max_retries):
            return pick("replan", "rollback", "retry", "ask_human")
        return pick("rollback", "ask_human", "isolate", "replan")

    # code_bug
    if attempt <= max_retries:
        return pick("retry", "replan", "ask_human")
    if attempt == max_retries + 1:
        return pick("replan", "rollback", "isolate", "ask_human")
    return pick("isolate", "ask_human", "rollback", "replan")
