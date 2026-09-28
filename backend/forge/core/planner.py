"""Hierarchical planning for non-technical goals.

The planner asks the model for a JSON plan, then falls back to a deterministic
decomposer when the model returns garbage. Small models often do. The fallback
still produces dependency-aware tasks with expected outputs and failure conditions.
"""

from __future__ import annotations

import re
from typing import Any

from forge.util import extract_json, shorten

META_HINTS = (
    "i am not a programmer",
    "i'm not a programmer",
    "i am not technical",
    "i'm not technical",
    "not a programmer",
)
CONSTRAINT_HINTS = (
    "keep add",
    "keep existing",
    "keep the existing",
    "don't break",
    "do not break",
    "without breaking",
    "must keep working",
    "keep add, list",
)
TEST_HINTS = (
    "unit test",
    "add tests",
    "add a unit test",
    "write tests",
    "include tests",
    "add tests for",
)

PLAN_SYSTEM = """PHASE: PLAN
You are the FORGE planner. Turn a plain-language software request into a small,
dependency-aware plan that a weak coding model can execute one task at a time.
Write tasks a non-engineer can read. Each task needs an expected output and
explicit failure conditions.
Return ONLY JSON with this shape:
{
  "summary": "one sentence",
  "assumptions": ["..."],
  "phases": [{"id": "implement", "title": "Make the change", "task_ids": ["t1"]}],
  "tasks": [
    {
      "id": "t1",
      "title": "short imperative",
      "description": "what to do, in plain language",
      "dependencies": [],
      "expected_output": "what a reviewer can observe when this task is done",
      "failure_conditions": ["how we will know this task failed"],
      "files_hint": ["relative/path.py"]
    }
  ]
}
Do not include markdown.
"""


def split_clauses(goal: str) -> list[str]:
    text = (goal or "").replace("\r", "")
    parts = re.split(r"\n+|(?<=[.!?])\s+", text)
    clauses: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        bits = re.split(r"\s+\band\b\s+", part, flags=re.IGNORECASE)
        if len(bits) > 1 and all(len(bit.strip()) > 28 for bit in bits):
            clauses.extend(bit.strip() for bit in bits)
        else:
            clauses.append(part)
    cleaned = []
    for clause in clauses:
        item = clause.strip(" .;")
        if len(item) > 8:
            cleaned.append(item)
    return cleaned


def _is_meta(clause: str) -> bool:
    low = clause.lower()
    return any(hint in low for hint in META_HINTS)


def _is_constraint(clause: str) -> bool:
    low = clause.lower()
    return any(hint in low for hint in CONSTRAINT_HINTS)


def _is_test(clause: str) -> bool:
    low = clause.lower()
    return any(hint in low for hint in TEST_HINTS)


def decompose_goal(goal: str, file_hints: list[str] | None = None) -> dict[str, Any]:
    """One-shot plan used directly and as the small-model fallback."""
    hints = list(file_hints or [])
    constraints: list[str] = []
    test_notes: list[str] = []
    actions: list[str] = []
    for clause in split_clauses(goal):
        if _is_meta(clause):
            continue
        if _is_constraint(clause):
            constraints.append(clause)
        elif _is_test(clause):
            test_notes.append(clause)
        else:
            actions.append(clause)
    if not actions:
        actions = [re.sub(r"\s+", " ", goal).strip() or "Apply the requested change"]

    tasks: list[dict[str, Any]] = []
    previous: str | None = None
    for index, action in enumerate(actions, start=1):
        task_id = f"t{index}"
        tasks.append(
            {
                "id": task_id,
                "title": shorten(action, 72),
                "description": action,
                "dependencies": [previous] if previous else [],
                "expected_output": action,
                "failure_conditions": [
                    *constraints,
                    "The expected output cannot be observed in the repository.",
                    "Behavior that was already working has changed.",
                ],
                "files_hint": hints[:4],
            }
        )
        previous = task_id

    test_id = f"t{len(tasks) + 1}"
    tasks.append(
        {
            "id": test_id,
            "title": "Add tests that prove the change",
            "description": test_notes[0]
            if test_notes
            else "Add or update automated tests that fail when the requested behavior is missing.",
            "dependencies": [task["id"] for task in tasks],
            "expected_output": "Automated tests fail if the new behavior is wrong and pass when it is right.",
            "failure_conditions": [
                "Tests were not added.",
                "Tests encode the wrong behavior and would pass even if the product is wrong.",
            ],
            "files_hint": hints[:4],
        }
    )
    impl_ids = [task["id"] for task in tasks if task["id"] != test_id]
    return {
        "summary": shorten(goal, 200),
        "assumptions": constraints
        or ["Existing tests describe behavior that must keep working."],
        "phases": [
            {"id": "implement", "title": "Make the change", "task_ids": impl_ids},
            {"id": "prove", "title": "Prove it works", "task_ids": [test_id]},
        ],
        "tasks": tasks,
    }


def single_task_plan(goal: str) -> dict[str, Any]:
    """Baseline path: the raw request is the only task, with no checklist."""
    return {
        "summary": shorten(goal, 200),
        "assumptions": [],
        "phases": [{"id": "do", "title": "Do the work", "task_ids": ["t1"]}],
        "tasks": [
            {
                "id": "t1",
                "title": "Apply the request",
                "description": goal.strip(),
                "dependencies": [],
                "expected_output": "",
                "failure_conditions": [],
                "files_hint": [],
            }
        ],
    }


def normalize_plan(data: dict[str, Any], file_hints: list[str] | None = None) -> dict[str, Any]:
    hints = list(file_hints or [])
    tasks_in = data.get("tasks") or []
    if not isinstance(tasks_in, list) or not tasks_in:
        raise ValueError("plan has no tasks")
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(tasks_in, start=1):
        if not isinstance(raw, dict):
            continue
        task_id = str(raw.get("id") or f"t{index}")
        if task_id in seen:
            task_id = f"{task_id}_{index}"
        seen.add(task_id)
        tasks.append(
            {
                "id": task_id,
                "title": shorten(str(raw.get("title") or raw.get("description") or f"Task {index}"), 80),
                "description": str(raw.get("description") or raw.get("title") or "").strip(),
                "dependencies": [str(item) for item in (raw.get("dependencies") or [])],
                "expected_output": str(raw.get("expected_output") or "").strip(),
                "failure_conditions": [str(item) for item in (raw.get("failure_conditions") or [])],
                "files_hint": [str(item) for item in (raw.get("files_hint") or hints[:4])],
            }
        )
    known = {task["id"] for task in tasks}
    for task in tasks:
        task["dependencies"] = [dep for dep in task["dependencies"] if dep in known and dep != task["id"]]
        if not task["expected_output"]:
            task["expected_output"] = task["description"]
        if not task["failure_conditions"]:
            task["failure_conditions"] = ["The expected output cannot be observed."]
    phases = data.get("phases")
    if not isinstance(phases, list) or not phases:
        phases = [{"id": "all", "title": "Work", "task_ids": [task["id"] for task in tasks]}]
    else:
        cleaned_phases = []
        for index, phase in enumerate(phases, start=1):
            if not isinstance(phase, dict):
                continue
            ids = [str(item) for item in (phase.get("task_ids") or []) if str(item) in known]
            cleaned_phases.append(
                {
                    "id": str(phase.get("id") or f"p{index}"),
                    "title": str(phase.get("title") or f"Phase {index}"),
                    "task_ids": ids,
                }
            )
        phases = cleaned_phases or [{"id": "all", "title": "Work", "task_ids": [task["id"] for task in tasks]}]
    assumptions = data.get("assumptions") or []
    if not isinstance(assumptions, list):
        assumptions = [str(assumptions)]
    return {
        "summary": str(data.get("summary") or shorten(tasks[0]["description"], 180)),
        "assumptions": [str(item) for item in assumptions],
        "phases": phases,
        "tasks": tasks,
    }


async def create_plan(
    goal: str,
    *,
    planning: bool,
    llm,
    repo_summary: str = "",
    file_hints: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return (plan, llm_call_or_none)."""
    if not planning:
        return single_task_plan(goal), None
    messages = [
        {"role": "system", "content": PLAN_SYSTEM},
        {
            "role": "user",
            "content": f"REPO SUMMARY:\n{repo_summary or 'No index yet.'}\n\nGOAL:\n{goal}",
        },
    ]
    response = await llm.complete(messages, temperature=0.1, max_tokens=1800, json_mode=True)
    call = {
        "phase": "plan",
        "provider": response.provider,
        "model": response.model,
        "prompt_preview": messages[-1]["content"][:800],
        "response_preview": response.text[:1500],
        "tokens_in": response.prompt_tokens,
        "tokens_out": response.completion_tokens,
        "latency_ms": int(response.latency_ms),
    }
    try:
        plan = normalize_plan(extract_json(response.text), file_hints)
    except (ValueError, TypeError, KeyError):
        plan = decompose_goal(goal, file_hints)
        plan["summary"] = f"{plan['summary']} (planner fallback)"
    return plan, call
