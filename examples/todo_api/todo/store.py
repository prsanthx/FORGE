"""In-memory todo store.

This module is intentionally small so a knowledge-graph index can show files,
symbols, imports, and tests without a framework.
"""

from __future__ import annotations


class TodoError(ValueError):
    """Raised when a todo operation is invalid."""


class TodoStore:
    """Collection of todos kept in process memory."""

    def __init__(self) -> None:
        self._items: dict[int, dict] = {}
        self._seq = 1

    def add(self, title: str) -> dict:
        """Create a todo. Empty titles are rejected."""
        cleaned = (title or "").strip()
        if not cleaned:
            raise TodoError("title required")
        item = {"id": self._seq, "title": cleaned, "done": False}
        self._items[self._seq] = item
        self._seq += 1
        return dict(item)

    def list(self, *, done: bool | None = None) -> list[dict]:
        """Return todos, optionally filtered by done."""
        items = [dict(item) for item in self._items.values()]
        if done is None:
            return items
        return [item for item in items if item["done"] is done]

    def get(self, todo_id: int) -> dict | None:
        """Return one todo, or None when the id is unknown."""
        item = self._items.get(todo_id)
        return dict(item) if item else None

    def remove(self, todo_id: int) -> bool:
        """Delete a todo. Return True if it existed."""
        return self._items.pop(todo_id, None) is not None
