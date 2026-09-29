"""Reason → tool → observation loop."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from forge.core.tools import execute_tool
from forge.kg.query import GraphRetriever
from forge.util import extract_json

EXECUTE_SYSTEM = """PHASE: EXECUTE
You are a small coding model working inside FORGE. You see one task, a compressed
context pack when the harness has one, and the results of earlier tool calls.
Decide the next tool. Return ONLY JSON of the form
{"thought": "short reason", "action": "tool_name", "args": {}}
Allowed actions and arguments:
- search: {"query": "text", "glob": "*.py"}
- read_file: {"path": "relative/path.py"}
- write_file: {"path": "relative/path.py", "content": "full file"}
- list_dir: {"path": "."}
- terminal: {"command": "pytest -q"}
- git: {"args": "status"}
- kg_query: {"query": "symbol or task text"}
- finish: {"summary": "what changed"}
Never invent a tool. Prefer reading a file before rewriting it. When you finish,
the repository must contain the behavior described in EXPECTED_OUTPUT.
When the user message includes SKILLS, treat them as constraints.
Extra names under TOOLS are real tools with the same JSON shape.
"""


def _enabled(cfg: dict[str, Any]) -> list[str]:
    tools = list((cfg.get("tools") or {}).get("enabled") or [])
    return tools


def build_prompt(
    *,
    goal: str,
    task: dict[str, Any],
    attempt: int,
    diagnosis: dict[str, Any] | None,
    steps: list[dict[str, Any]],
    tools: list[str],
    context_pack: str,
    failure_memory: list[dict[str, Any]],
    planning: bool,
    skill_block: str = "",
    extra_tools: list[str] | None = None,
) -> str:
    sections = [
        f"GOAL:\n{goal.strip()}",
        f"ATTEMPT: {attempt}",
        "CURRENT_TASK:\n"
        + f"{task.get('title')}\n{task.get('description')}",
    ]
    if planning and (task.get("expected_output") or "").strip():
        sections.append(f"EXPECTED_OUTPUT:\n{task['expected_output'].strip()}")
    conditions = task.get("failure_conditions") or []
    if planning and conditions:
        lines = "\n".join(f"- {item}" for item in conditions)
        sections.append(f"CHECKLIST:\n{lines}")
    if context_pack:
        sections.append(context_pack if context_pack.startswith("CONTEXT PACK") else f"CONTEXT PACK:\n{context_pack}")
    if failure_memory:
        mem = "\n".join(
            f"- {item.get('failure_class')} on {item.get('task_key')}: {(item.get('evidence') or '')[:180]}"
            for item in failure_memory[:5]
        )
        sections.append(f"FAILURE_MEMORY:\n{mem}")
    if diagnosis:
        sections.append(
            "DIAGNOSIS:\n"
            + f"class: {diagnosis.get('failure_class')}\n"
            + f"why: {diagnosis.get('why')}\n"
            + f"evidence: {diagnosis.get('evidence')}"
        )
    else:
        sections.append("DIAGNOSIS:\nnone")
    listed = list(tools)
    for name in extra_tools or []:
        if name not in listed:
            listed.append(name)
    tool_lines = "\n".join(f"- {name}" for name in listed)
    sections.append(f"TOOLS:\n{tool_lines}")
    if skill_block.strip():
        sections.append(skill_block if skill_block.startswith("SKILLS:") else f"SKILLS:\n{skill_block}")
    public_steps = []
    for step in steps[-8:]:
        public_steps.append(
            {
                "action": step["action"],
                "args": {key: value for key, value in step.get("args", {}).items() if key != "content"},
                "ok": step.get("ok"),
                "result": (step.get("result") or "")[:3500],
            }
        )
    sections.append("PRIOR_STEPS_JSON:\n" + json.dumps(public_steps))
    return "\n\n".join(sections)


def parse_action(text: str) -> tuple[str, dict[str, Any], str]:
    data = extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("action must be a JSON object")
    action = str(data.get("action") or data.get("tool") or "").strip()
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    if not args:
        args = {
            key: value
            for key, value in data.items()
            if key not in {"thought", "action", "tool", "args"}
        }
    if not action:
        raise ValueError("missing action")
    return action, args, str(data.get("thought") or "")


async def execute_task(
    *,
    llm,
    cfg: dict[str, Any],
    workspace: Path,
    goal: str,
    task: dict[str, Any],
    attempt: int,
    diagnosis: dict[str, Any] | None,
    retriever: GraphRetriever | None,
    failure_memory: list[dict[str, Any]],
    on_llm,
    on_tool,
    skill_block: str = "",
    extra_tools: list[str] | None = None,
    mcp_call: Callable[[str, dict[str, Any]], tuple[bool, str]] | None = None,
) -> dict[str, Any]:
    tools = _enabled(cfg)
    mcp_names = [name for name in (extra_tools or []) if name not in tools]
    visible = tools + mcp_names
    planning = bool((cfg.get("features") or {}).get("planning"))
    use_pack = bool((cfg.get("features") or {}).get("context_packs")) and retriever is not None
    budget = int((cfg.get("executor") or {}).get("context_char_budget") or 4000)
    context_pack = ""
    if use_pack:
        context_pack = retriever.context_pack(
            f"{task.get('title', '')}\n{task.get('description', '')}\n{goal}",
            budget=min(budget, 3200),
        )
    max_steps = int((cfg.get("executor") or {}).get("max_steps_per_task") or 8)
    steps: list[dict[str, Any]] = []
    changed: list[str] = []
    for _ in range(max_steps):
        prompt = build_prompt(
            goal=goal,
            task=task,
            attempt=attempt,
            diagnosis=diagnosis,
            steps=steps,
            tools=visible,
            context_pack=context_pack,
            failure_memory=failure_memory if (cfg.get("features") or {}).get("failure_memory") else [],
            planning=planning,
            skill_block=skill_block,
        )
        response = await llm.complete(
            [
                {"role": "system", "content": EXECUTE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=float((cfg.get("llm") or {}).get("temperature") or 0.2),
            max_tokens=int((cfg.get("llm") or {}).get("max_tokens") or 4096),
            json_mode=True,
        )
        await on_llm(response, prompt, "execute")
        try:
            action, args, thought = parse_action(response.text)
        except (ValueError, TypeError) as exc:
            steps.append({"action": "invalid", "args": {}, "ok": False, "result": str(exc), "thought": ""})
            continue
        if action == "finish":
            return {
                "ok": True,
                "summary": str(args.get("summary") or thought or "finished"),
                "changed": changed,
                "steps": len(steps),
            }
        if action in mcp_names:
            started = time.perf_counter()
            if mcp_call is None:
                ok, result = False, f"tool {action} is not connected"
            else:
                ok, result = mcp_call(action, args)
            elapsed = int((time.perf_counter() - started) * 1000)
            await on_tool(action, args, ok, result, elapsed)
            steps.append({"action": action, "args": args, "ok": ok, "result": result, "thought": thought})
            continue
        if action not in tools:
            result = f"tool {action} is disabled in this config"
            steps.append({"action": action, "args": args, "ok": False, "result": result, "thought": thought})
            await on_tool(action, args, False, result, 0)
            continue
        # Avoid logging full file bodies twice; the tool call record keeps a preview.
        ok, result, elapsed = execute_tool(action, args, root=workspace, retriever=retriever)
        await on_tool(action, args, ok, result, elapsed)
        if action == "write_file" and ok:
            changed.append(str(args.get("path")))
        steps.append({"action": action, "args": args, "ok": ok, "result": result, "thought": thought})
    return {
        "ok": False,
        "summary": "step budget exhausted before finish",
        "changed": changed,
        "steps": len(steps),
    }
