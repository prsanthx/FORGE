"""Skills, MCP discovery, and the tool list given to the model."""

from __future__ import annotations

from forge.core.executor import build_prompt
from forge.db import Database
from forge.studio import (
    call_mcp_tool,
    create_skill,
    install_demo,
    load_prompt_extras,
    snapshot,
    update_mcp,
    update_skill,
)


def test_seed_skills_and_tool_count(tmp_path):
    db = Database(tmp_path / "forge.db")
    view = snapshot(db, "full_forge")
    names = [skill["name"] for skill in view["skills"]]
    assert names == ["plan_the_edit", "read_before_rewrite", "narrow_diff"]
    assert view["summary"]["skills_enabled"] == 3
    assert view["summary"]["builtin_enabled"] == 7
    assert view["summary"]["finish"] == 1
    assert view["summary"]["mcp_tools"] == 0
    assert view["summary"]["tools_in_prompt"] == 8
    assert "finish" in view["prompt_tools"]
    again = snapshot(db, "baseline")
    assert len(again["skills"]) == 3
    assert again["summary"]["builtin_enabled"] == 2
    assert again["summary"]["tools_in_prompt"] == 3


def test_skill_toggle_changes_prompt_block(tmp_path):
    db = Database(tmp_path / "forge.db")
    created = create_skill(db, name="keep_notes", description="Notes", body="Write a one line note when you finish.")
    block, _names = load_prompt_extras(db)
    assert "keep_notes" in block
    assert block.startswith("SKILLS:")
    update_skill(db, created["id"], {"enabled": False})
    block, _names = load_prompt_extras(db)
    assert "keep_notes" not in block


def test_demo_mcp_is_offered_to_the_model(tmp_path):
    db = Database(tmp_path / "forge.db")
    server = install_demo(db)
    assert server["status"] == "connected"
    assert server["enabled"] is True
    prompt_names = [tool["prompt_name"] for tool in server["tools"]]
    assert "local_demo_repo_notes" in prompt_names
    assert "local_demo_ask_oracle" in prompt_names
    view = snapshot(db, "full_forge")
    assert view["summary"]["mcp_tools"] == 2
    assert view["summary"]["tools_in_prompt"] == 10
    block, names = load_prompt_extras(db)
    prompt = build_prompt(
        goal="Add a note",
        task={"title": "note", "description": "add a note"},
        attempt=1,
        diagnosis=None,
        steps=[],
        tools=["search", "read_file"],
        context_pack="",
        failure_memory=[],
        planning=False,
        skill_block=block,
        extra_tools=names,
    )
    assert "- local_demo_repo_notes" in prompt
    assert "- local_demo_ask_oracle" in prompt
    assert prompt.index("TOOLS:") < prompt.index("SKILLS:")
    assert "plan_the_edit" in prompt
    ok, text = call_mcp_tool(db, "local_demo_ask_oracle", {"question": "what is the answer"})
    assert ok
    assert "benchmarks" not in text.lower()
    assert "answer key" in text.lower()
    update_mcp(db, server["id"], {"enabled": False})
    _block, names = load_prompt_extras(db)
    assert names == []
