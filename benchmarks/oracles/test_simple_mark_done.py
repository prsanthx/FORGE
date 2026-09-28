"""Independent check. The agent does not see this file."""

from todo.store import TodoStore


def test_mark_done_sets_true():
    store = TodoStore()
    item = store.add("read spec")
    updated = store.mark_done(item["id"])
    assert updated["done"] is True
    assert store.get(item["id"])["done"] is True
