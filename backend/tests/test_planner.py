"""Planner: non-technical goals become dependency-aware tasks."""

import asyncio

from forge.core.planner import create_plan, decompose_goal, normalize_plan
from forge.llm.base import LLMResponse


GOAL = (
    "I'm not technical. I need the todo list to let me mark an item done, "
    "and I need each item to have a priority. "
    "Blank titles should be rejected. "
    "Please add tests."
)


def test_decompose_nontechnical_goal_has_dependencies_and_failures():
    plan = decompose_goal(GOAL, file_hints=["todo/store.py"])
    assert len(plan["tasks"]) >= 3
    assert plan["phases"]
    ids = {task["id"] for task in plan["tasks"]}
    for task in plan["tasks"]:
        assert task["expected_output"]
        assert task["failure_conditions"]
        for dep in task["dependencies"]:
            assert dep in ids
            assert dep != task["id"]
    test_task = plan["tasks"][-1]
    assert test_task["dependencies"]
    assert "test" in test_task["title"].lower() or "test" in test_task["description"].lower()
    # Implementation tasks form a chain a non-engineer can follow in order.
    impl = [task for task in plan["tasks"] if task["id"] != test_task["id"]]
    assert impl[0]["dependencies"] == []
    if len(impl) > 1:
        assert impl[1]["dependencies"] == [impl[0]["id"]]


def test_garbage_model_output_falls_back_to_decomposer():
    class Garbage:
        async def complete(self, messages, **kwargs):
            return LLMResponse(
                text="sure, I'll get right on that ```not json```",
                prompt_tokens=3,
                completion_tokens=4,
                latency_ms=1,
                provider="script",
                model="bad",
            )

    plan, call = asyncio.run(create_plan(GOAL, planning=True, llm=Garbage(), file_hints=["todo/store.py"]))
    assert call["phase"] == "plan"
    assert len(plan["tasks"]) >= 3
    assert "fallback" in plan["summary"]


def test_planning_disabled_is_a_single_raw_task():
    plan, call = asyncio.run(create_plan("Ship the button.", planning=False, llm=None))
    assert call is None
    assert len(plan["tasks"]) == 1
    assert plan["tasks"][0]["expected_output"] == ""
    assert plan["tasks"][0]["failure_conditions"] == []


def test_normalize_repairs_missing_fields():
    plan = normalize_plan({"tasks": [{"title": "Add mark_done", "dependencies": ["missing"]}]})
    task = plan["tasks"][0]
    assert task["expected_output"]
    assert task["failure_conditions"]
    assert task["dependencies"] == []
