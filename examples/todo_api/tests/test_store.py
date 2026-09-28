"""Behavior that already works and must survive new changes."""

from todo.store import TodoError, TodoStore


def test_add_and_get():
    store = TodoStore()
    item = store.add("milk")
    assert item["title"] == "milk"
    assert item["done"] is False
    assert store.get(item["id"])["title"] == "milk"


def test_list_open_items():
    store = TodoStore()
    store.add("a")
    store.add("b")
    assert len(store.list()) == 2
    assert store.list(done=True) == []
    assert len(store.list(done=False)) == 2


def test_remove():
    store = TodoStore()
    item = store.add("a")
    assert store.remove(item["id"]) is True
    assert store.get(item["id"]) is None
    assert store.remove(item["id"]) is False


def test_blank_title_rejected_on_add():
    store = TodoStore()
    try:
        store.add("   ")
        raised = False
    except TodoError:
        raised = True
    assert raised
