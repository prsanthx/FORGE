# Todo API sample

A small in-memory todo store used by FORGE benchmarks. Connect this directory as a local repo, index the knowledge graph, then run a goal from the dashboard or the CLI.

```bash
python -m forge.cli run \
  --repo examples/todo_api \
  --config full_forge \
  --goal "Please add a way to mark a todo as done. When a todo is marked done, its done flag becomes true."
```

Package layout:

- `todo/store.py` — `TodoStore` (`add`, `list`, `get`, `remove`)
- `todo/cli.py` — tiny command line over the store
- `tests/test_store.py` — behavior that must keep working
