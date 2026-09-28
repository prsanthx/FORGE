"""Independent checks for the long-horizon todo goal."""

from todo.store import TodoError, TodoStore


def test_mark_done_sets_true():
    store = TodoStore()
    item = store.add("read spec")
    assert store.mark_done(item["id"])["done"] is True


def test_update_rejects_blank_title():
    store = TodoStore()
    item = store.add("old")
    assert store.update(item["id"], title="new")["title"] == "new"
    raised = False
    try:
        store.update(item["id"], title=" ")
    except TodoError:
        raised = True
    assert raised


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


def test_persists_across_instances(tmp_path):
    path = tmp_path / "todos.json"
    store = TodoStore(path=str(path))
    store.add("milk")
    reopened = TodoStore(path=str(path))
    titles = [item["title"] for item in reopened.list()]
    assert titles == ["milk"]


def test_filter_by_priority():
    store = TodoStore()
    low = store.add("low-item")
    store.add("med-item")
    store.update(low["id"], priority="low")
    found = store.list(priority="low")
    assert [item["title"] for item in found] == ["low-item"]
