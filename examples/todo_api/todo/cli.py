"""Command line over TodoStore. Used so the graph has an import edge."""

from __future__ import annotations

import argparse

from todo.store import TodoError, TodoStore


def build_store() -> TodoStore:
    """Construct the default in-memory store."""
    return TodoStore()


def main(argv: list[str] | None = None) -> int:
    """Add or list todos. Returns a process status code."""
    parser = argparse.ArgumentParser(prog="todo")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("title")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    store = build_store()
    try:
        if args.cmd == "add":
            item = store.add(args.title)
            print(f"{item['id']}: {item['title']}")
        else:
            for item in store.list():
                mark = "x" if item["done"] else " "
                print(f"[{mark}] {item['id']}: {item['title']}")
    except TodoError as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
