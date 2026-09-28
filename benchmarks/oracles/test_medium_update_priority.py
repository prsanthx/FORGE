"""Independent checks for title updates and priority."""

from todo.store import TodoError, TodoStore


def test_update_changes_title():
    store = TodoStore()
    item = store.add("old")
    updated = store.update(item["id"], title="new")
    assert updated["title"] == "new"
    assert store.get(item["id"])["title"] == "new"


def test_update_rejects_blank_title():
    store = TodoStore()
    item = store.add("old")
    raised = False
    try:
        store.update(item["id"], title="   ")
    except TodoError:
        raised = True
    assert raised
    assert store.get(item["id"])["title"] == "old"


def test_priority_default_and_validation():
    store = TodoStore()
    item = store.add("old")
    assert item["priority"] == "med"
    raised = False
    try:
        store.update(item["id"], priority="urgent")
    except TodoError:
        raised = True
    assert raised
    assert store.get(item["id"])["priority"] == "med"
