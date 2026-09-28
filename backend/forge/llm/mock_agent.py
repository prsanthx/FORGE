"""Deterministic stand-in for a small coding model.

MockLLM is not a table of benchmark scores. It is a tool-using policy with a
small context budget:

- Without a structured expected-output checklist, it overwrites the todo store
  from incomplete memory (it drops ``remove``) and writes tests that agree with
  its bugs. That is the cascade the slides describe.
- With a plan checklist it follows easy requirements and still slips on tricky
  ones (blank titles, priority validation, reload, filters) until verification
  output names the miss.
- A context pack is what tells it the real file path and signatures before it
  has listed the tree.

Point the same harness at Ollama or another provider to replace this policy
with a real model. Metrics always come from the run.
"""

from __future__ import annotations

import ast
import json
import re
import time
from typing import Any

from forge.core.planner import decompose_goal
from forge.core.recovery import classify_failure
from forge.llm.base import LLMResponse, messages_text
from forge.util import estimate_tokens

TRICKY = {"reject_blank", "priority_validate", "persist", "filter_priority"}
ALLOWED_PRIORITY = '{"low", "med", "high"}'


def _section(prompt: str, name: str) -> str:
    """Slice a `NAME:` block. Headers may contain spaces (CONTEXT PACK)."""
    pattern = rf"(?:^|\n){re.escape(name)}:\n(.*?)(?=\n[A-Z][A-Z0-9 _]*:\n|\Z)"
    match = re.search(pattern, prompt, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def detect_features(text: str) -> list[str]:
    low = (text or "").lower()
    found: list[str] = []

    def add(name: str, cond: bool) -> None:
        if cond and name not in found:
            found.append(name)

    add(
        "mark_done",
        bool(
            re.search(
                r"mark(?:ed|ing)?(?:[_\s-]+(?:a|the|an)\s+(?:todo\s+)?)?(?:as\s+)?done|mark[_\s-]?done|done flag",
                low,
            )
        ),
    )
    add("update_title", bool(re.search(r"\bupdate\b|change a todo's title|change the title|todo's title", low)))
    add("reject_blank", "blank" in low or "empty title" in low)
    add("priority_field", "priority" in low)
    add(
        "priority_validate",
        "priority" in low and any(token in low for token in ("reject", "invalid", "other priority", "any other")),
    )
    add("persist", bool(re.search(r"persist|json file|still there|new store", low)))
    add("filter_priority", "filter" in low and "priority" in low)
    return found


def _fixes(prompt: str) -> set[str]:
    diagnosis = _section(prompt, "DIAGNOSIS")
    if not diagnosis or diagnosis.lower() in {"none", "n/a"}:
        return set()
    low = diagnosis.lower()
    fixes: set[str] = set()
    if "blank" in low or "title required" in low:
        fixes.add("reject_blank")
    if "priority" in low:
        fixes.add("priority_validate")
        fixes.add("priority_field")
    if "persist" in low or "json" in low or "reload" in low:
        fixes.add("persist")
    if "filter" in low:
        fixes.add("filter_priority")
    if "mark_done" in low or ("done" in low and "false" in low):
        fixes.add("mark_done")
    if "remove" in low:
        fixes.add("preserve_remove")
    return fixes


def _parse_markers(source: str) -> tuple[set[str], set[str]] | None:
    features: set[str] = set()
    bugs: set[str] = set()
    found = False
    for line in source.splitlines()[:8]:
        if line.startswith("# features:"):
            features = {part.strip() for part in line.split(":", 1)[1].split(",") if part.strip()}
            found = True
        elif line.startswith("# bugs:"):
            bugs = {part.strip() for part in line.split(":", 1)[1].split(",") if part.strip()}
            found = True
    if not found:
        return None
    return features, bugs


def _infer_from_source(source: str) -> tuple[set[str], set[str], bool]:
    features: set[str] = set()
    if "def mark_done" in source:
        features.add("mark_done")
    if "def update" in source:
        features.add("update_title")
    if "def update" in source and "title required" in source:
        features.add("reject_blank")
    if 'item["priority"] = "med"' in source or "item['priority'] = 'med'" in source:
        features.add("priority_field")
    if "invalid priority" in source:
        features.add("priority_validate")
    if "json.loads" in source:
        features.add("persist")
    if "priority is not None" in source:
        features.add("filter_priority")
    bugs: set[str] = set()
    if "def mark_done" in source and 'item["done"] = False' in source:
        bugs.add("mark_done")
    preserve_remove = bool(re.search(r"def remove\(", source))
    return features, bugs, preserve_remove


def _steps(prompt: str) -> list[dict[str, Any]]:
    raw = _section(prompt, "PRIOR_STEPS_JSON")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _tools(prompt: str) -> list[str]:
    block = _section(prompt, "TOOLS")
    names = re.findall(r"- ([a-z_]+)", block)
    return names or ["write_file"]


def _read_source(steps: list[dict[str, Any]]) -> str:
    for step in reversed(steps):
        if step.get("action") == "read_file":
            result = step.get("result") or ""
            if "\n---\n" in result:
                return result.split("\n---\n", 1)[1]
            return result
    return ""


def _symbols_from_steps(steps: list[dict[str, Any]]) -> set[str]:
    symbols: set[str] = set()
    for step in steps:
        result = step.get("result") or ""
        match = re.search(r"symbols:\s*(.*)", result)
        if match:
            symbols.update(part.strip() for part in match.group(1).split(",") if part.strip() and part.strip() != "(none)")
    return symbols


def decide_edit(prompt: str) -> tuple[str, str, str] | None:
    """Return (path, source, tests) or None when this step should not edit."""
    goal = _section(prompt, "GOAL")
    expected = _section(prompt, "EXPECTED_OUTPUT")
    checklist = _section(prompt, "CHECKLIST")
    current = _section(prompt, "CURRENT_TASK")
    structured = bool(expected.strip())
    focus = "\n".join([current, expected, checklist]) if structured else goal
    requested = detect_features(focus)
    if structured and not requested:
        return None
    steps = _steps(prompt)
    source = _read_source(steps)
    symbols = _symbols_from_steps(steps)
    fixes = _fixes(prompt)
    present: set[str] = set()
    old_bugs: set[str] = set()
    preserve_remove = "remove" in symbols or "preserve_remove" in fixes
    if source:
        markers = _parse_markers(source)
        if markers:
            present, old_bugs = markers
        else:
            inferred, inferred_bugs, saw_remove = _infer_from_source(source)
            present |= inferred
            old_bugs |= inferred_bugs
            preserve_remove = preserve_remove or saw_remove
    if "todo/store.py" in prompt:
        path = "todo/store.py"
    else:
        path = "store.py"
    features = set(present) | set(requested)
    if not structured:
        features = set(requested)
        preserve_remove = False
    bugs: set[str] = set()
    for feature in features:
        if feature in fixes:
            continue
        if not structured:
            bugs.add(feature)
        elif feature in requested and feature in TRICKY:
            bugs.add(feature)
        elif feature in old_bugs:
            bugs.add(feature)
    store = render_store(features, bugs, preserve_remove=preserve_remove or "remove" in symbols and structured)
    tests = render_tests(features, bugs, structured=structured)
    return path, store, tests


def render_store(features: set[str], bugs: set[str], *, preserve_remove: bool) -> str:
    feature_line = ",".join(sorted(features))
    bug_line = ",".join(sorted(bugs))
    needs_update = bool(
        features & {"update_title", "reject_blank", "priority_field", "priority_validate", "filter_priority"}
    )
    needs_priority = bool(features & {"priority_field", "priority_validate", "filter_priority"})
    persist = "persist" in features
    filt = "filter_priority" in features
    lines: list[str] = [
        f"# features: {feature_line}",
        f"# bugs: {bug_line}",
        '"""Todo store edited by the coding agent."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    if persist:
        lines += ["import json", "from pathlib import Path", ""]
    lines += [
        "class TodoError(ValueError):",
        '    """Invalid todo operation."""',
        "",
        "class TodoStore:",
        '    """Todo collection."""',
        "",
    ]
    if persist:
        lines += [
            "    def __init__(self, path: str | None = None) -> None:",
            "        self._items: dict[int, dict] = {}",
            "        self._seq = 1",
            "        self._path = path",
            "        if path:",
            "            self._load()",
            "",
        ]
    else:
        lines += [
            "    def __init__(self) -> None:",
            "        self._items: dict[int, dict] = {}",
            "        self._seq = 1",
            "",
        ]
    lines += [
        "    def add(self, title: str) -> dict:",
        '        cleaned = (title or "").strip()',
        "        if not cleaned:",
        '            raise TodoError("title required")',
        '        item = {"id": self._seq, "title": cleaned, "done": False}',
    ]
    if needs_priority and "priority_field" not in bugs:
        lines.append('        item["priority"] = "med"')
    lines += [
        "        self._items[self._seq] = item",
        "        self._seq += 1",
    ]
    if persist:
        lines.append("        self._save()")
    lines += [
        "        return dict(item)",
        "",
        "    def list(self, *, done: bool | None = None" + (", priority: str | None = None" if filt else "") + ") -> list[dict]:",
        "        items = [dict(item) for item in self._items.values()]",
        "        if done is not None:",
        '            items = [item for item in items if item["done"] is done]',
    ]
    if filt and "filter_priority" not in bugs:
        lines += [
            "        if priority is not None:",
            '            items = [item for item in items if item.get("priority") == priority]',
        ]
    lines += [
        "        return items",
        "",
        "    def get(self, todo_id: int) -> dict | None:",
        "        item = self._items.get(todo_id)",
        "        return dict(item) if item else None",
        "",
    ]
    if preserve_remove:
        lines += [
            "    def remove(self, todo_id: int) -> bool:",
            "        existed = self._items.pop(todo_id, None) is not None",
        ]
        if persist:
            lines += [
                "        if existed:",
                "            self._save()",
            ]
        lines += [
            "        return existed",
            "",
        ]
    if "mark_done" in features:
        done_value = "False" if "mark_done" in bugs else "True"
        lines += [
            "    def mark_done(self, todo_id: int) -> dict:",
            "        item = self._items.get(todo_id)",
            "        if item is None:",
            '            raise TodoError("not found")',
            f'        item["done"] = {done_value}',
        ]
        if persist:
            lines.append("        self._save()")
        lines += [
            "        return dict(item)",
            "",
        ]
    if needs_update:
        lines += [
            "    def update(",
            "        self,",
            "        todo_id: int,",
            "        *,",
            "        title: str | None = None,",
            "        priority: str | None = None,",
            "        done: bool | None = None,",
            "    ) -> dict:",
            "        item = self._items.get(todo_id)",
            "        if item is None:",
            '            raise TodoError("not found")',
            "        if title is not None:",
        ]
        if "update_title" in bugs:
            lines.append('            item["title"] = item["title"] + "!"')
        elif "reject_blank" in features and "reject_blank" not in bugs:
            lines += [
                "            cleaned = title.strip()",
                "            if not cleaned:",
                '                raise TodoError("title required")',
                '            item["title"] = cleaned',
            ]
        else:
            lines += [
                "            cleaned = title.strip()",
                '            item["title"] = cleaned',
            ]
        if needs_priority and "priority_field" not in bugs:
            lines.append("        if priority is not None:")
            if "priority_validate" in features and "priority_validate" not in bugs:
                lines += [
                    f"            if priority not in {ALLOWED_PRIORITY}:",
                    '                raise TodoError("invalid priority")',
                ]
            lines.append('            item["priority"] = priority')
        lines.append("        if done is not None:")
        lines.append('            item["done"] = bool(done)')
        if persist:
            lines.append("        self._save()")
        lines += [
            "        return dict(item)",
            "",
        ]
    if persist:
        lines += [
            "    def _save(self) -> None:",
            "        if not self._path:",
            "            return",
            '        payload = {"seq": self._seq, "items": list(self._items.values())}',
            "        Path(self._path).write_text(json.dumps(payload))",
            "",
            "    def _load(self) -> None:",
            "        if not self._path:",
            "            return",
        ]
        if "persist" in bugs:
            lines += [
                "        return",
            ]
        else:
            lines += [
                "        file = Path(self._path)",
                "        if not file.exists():",
                "            return",
                '        data = json.loads(file.read_text() or "{}")',
                '        self._seq = int(data.get("seq", 1))',
                "        self._items = {}",
                '        for raw in data.get("items", []):',
                '            self._items[int(raw["id"])] = dict(raw)',
            ]
    source = "\n".join(lines) + "\n"
    ast.parse(source)
    return source


def render_tests(features: set[str], bugs: set[str], *, structured: bool) -> str:
    """Structured plans assert the real requirement. Unstructured edits assert the bug."""

    def correct(name: str) -> bool:
        return structured or name not in bugs

    parts = [
        '"""Tests written by the coding agent."""',
        "",
        "import pytest",
        "",
        "from todo.store import TodoError, TodoStore",
        "",
    ]
    if "mark_done" in features:
        if correct("mark_done") and "mark_done" not in bugs:
            assertion = "assert got['done'] is True"
        elif structured:
            assertion = "assert got['done'] is True"
        else:
            assertion = "assert got['done'] is False"
        parts += [
            "def test_mark_done_flag():",
            "    store = TodoStore()",
            '    item = store.add("a")',
            "    got = store.mark_done(item['id'])",
            f"    {assertion}",
            "",
        ]
    if "update_title" in features or "reject_blank" in features:
        if structured or "update_title" not in bugs:
            parts += [
                "def test_update_changes_title():",
                "    store = TodoStore()",
                '    item = store.add("old")',
                '    assert store.update(item["id"], title="new")["title"] == "new"',
                "",
            ]
        else:
            parts += [
                "def test_update_changes_title():",
                "    store = TodoStore()",
                '    item = store.add("old")',
                '    assert store.update(item["id"], title="new")["title"] == "old!"',
                "",
            ]
    if "reject_blank" in features:
        if structured or "reject_blank" not in bugs:
            parts += [
                "def test_update_rejects_blank_title():",
                "    store = TodoStore()",
                '    item = store.add("keep")',
                '    with pytest.raises(TodoError):',
                '        store.update(item["id"], title="  ")',
                '    assert store.get(item["id"])["title"] == "keep"',
                "",
            ]
        else:
            parts += [
                "def test_update_rejects_blank_title():",
                "    store = TodoStore()",
                '    item = store.add("keep")',
                '    store.update(item["id"], title="  ")',
                '    assert store.get(item["id"])["title"] == ""',
                "",
            ]
    if "priority_field" in features or "priority_validate" in features:
        if structured or "priority_field" not in bugs:
            parts += [
                "def test_priority_defaults_med():",
                "    store = TodoStore()",
                '    assert store.add("a")["priority"] == "med"',
                "",
            ]
        if "priority_validate" in features and (structured or "priority_validate" not in bugs):
            parts += [
                "def test_priority_rejects_unknown_value():",
                "    store = TodoStore()",
                '    item = store.add("a")',
                "    with pytest.raises(TodoError):",
                '        store.update(item["id"], priority="urgent")',
                '    assert store.get(item["id"])["priority"] == "med"',
                "",
            ]
    if "persist" in features and (structured or "persist" not in bugs):
        parts += [
            "def test_persists_across_instances(tmp_path):",
            '    path = tmp_path / "todos.json"',
            "    store = TodoStore(path=str(path))",
            '    store.add("milk")',
            "    again = TodoStore(path=str(path))",
            '    assert [item["title"] for item in again.list()] == ["milk"]',
            "",
        ]
    if "filter_priority" in features and (structured or "filter_priority" not in bugs):
        parts += [
            "def test_filter_list_by_priority():",
            "    store = TodoStore()",
            '    low = store.add("low-item")',
            '    store.add("med-item")',
            '    store.update(low["id"], priority="low")',
            '    assert [item["title"] for item in store.list(priority="low")] == ["low-item"]',
            "",
        ]
    source = "\n".join(parts) + "\n"
    ast.parse(source)
    return source


def _action(thought: str, action: str, **args: Any) -> str:
    return json.dumps({"thought": thought, "action": action, "args": args})


class MockLLM:
    name = "mock"
    model = "mock-small"

    def __init__(self, model: str = "mock-small"):
        self.model = model or "mock-small"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> LLMResponse:
        started = time.perf_counter()
        prompt = messages_text(messages)
        system = messages[0].get("content", "") if messages else ""
        if "PHASE: PLAN" in system:
            goal = _section(prompt, "GOAL") or prompt
            text = json.dumps(decompose_goal(goal))
        elif "PHASE: DIAGNOSE" in system:
            attempt = 1
            match = re.search(r"ATTEMPT:\s*(\d+)", prompt)
            if match:
                attempt = int(match.group(1))
            output = _section(prompt, "OUTPUT") or prompt
            text = json.dumps(classify_failure(output, attempt))
        else:
            text = self._execute(prompt)
        elapsed = (time.perf_counter() - started) * 1000
        return LLMResponse(
            text=text,
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(text),
            latency_ms=elapsed,
            provider=self.name,
            model=self.model,
            estimated_tokens=True,
        )

    async def health(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": True, "detail": "mock model is local and deterministic"}

    def _execute(self, prompt: str) -> str:
        tools = set(_tools(prompt))
        steps = _steps(prompt)
        done = [step.get("action") for step in steps]
        wrote_store = any(
            step.get("action") == "write_file" and str(step.get("args", {}).get("path", "")).endswith("store.py")
            for step in steps
        )
        wrote_tests = any(
            step.get("action") == "write_file" and str(step.get("args", {}).get("path", "")).endswith("test_requested.py")
            for step in steps
        )
        if "kg_query" in tools and "kg_query" not in done:
            query = _section(prompt, "CURRENT_TASK") or _section(prompt, "GOAL")
            return _action("Look up symbols before editing.", "kg_query", query=query[:240])
        if "list_dir" in tools and "list_dir" not in done:
            return _action("See which files exist.", "list_dir", path=".")
        seen_store = "todo/store.py" in prompt
        if "read_file" in tools and "read_file" not in done and seen_store:
            return _action("Read the store before changing it.", "read_file", path="todo/store.py")
        edit = decide_edit(prompt)
        if "write_file" in tools and edit and not wrote_store:
            path, source, _tests = edit
            return _action("Write the store for this task.", "write_file", path=path, content=source)
        if "write_file" in tools and edit and not wrote_tests:
            _path, _source, tests = edit
            return _action("Write tests for the behavior I think I implemented.", "write_file", path="tests/test_requested.py", content=tests)
        if not edit and "write_file" not in done and "FORGE_NOTES.md" not in "".join(done):
            # Generic fallback for goals this demo model does not know how to code.
            if "write_file" in tools and not detect_features(_section(prompt, "GOAL") + _section(prompt, "EXPECTED_OUTPUT")):
                note = "# FORGE notes\n\n" + (_section(prompt, "CURRENT_TASK") or _section(prompt, "GOAL")) + "\n"
                return _action("This goal is outside the todo-store skills of the mock model.", "write_file", path="FORGE_NOTES.md", content=note)
        summary = "Finished the current task."
        if edit is None:
            summary = "No code change was required for this step."
        return _action(summary, "finish", summary=summary)
