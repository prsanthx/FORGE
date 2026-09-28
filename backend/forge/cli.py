"""Command line for index, run, benchmark, and the API server."""

from __future__ import annotations

import argparse
import asyncio
import json

import uvicorn

from forge.benchmark.runner import format_table, run_benchmark
from forge.service import ForgeService
from forge.settings import EXAMPLE_REPO, load_config


def _repo_for_path(service: ForgeService, path: str):
    resolved = str(__import__("pathlib").Path(path).expanduser().resolve())
    for repo in service.db.list_repos():
        if repo["path"] == resolved and repo["source"] == "local":
            return service.db.get_repo_raw(repo["id"])
    created = service.connect_local(resolved)
    return service.db.get_repo_raw(created["id"])


def main() -> None:
    parser = argparse.ArgumentParser(prog="forge", description="FORGE coding harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    index = sub.add_parser("index", help="connect a local repo and build its knowledge graph")
    index.add_argument("path")

    run = sub.add_parser("run", help="run one goal")
    run.add_argument("--repo", required=True)
    run.add_argument("--config", default="full_forge")
    run.add_argument("--goal", required=True)
    run.add_argument("--provider", default=None)
    run.add_argument("--model", default=None)

    bench = sub.add_parser("benchmark", help="run the ablation matrix")
    bench.add_argument("--repo", default=str(EXAMPLE_REPO))
    bench.add_argument(
        "--configs",
        default="baseline,planning,planning_verify,full_forge",
        help="comma-separated config names",
    )
    bench.add_argument("--tasks", default="", help="comma-separated task ids; default is all")

    serve = sub.add_parser("serve", help="start the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    if args.cmd == "serve":
        uvicorn.run("forge.main:app", host=args.host, port=args.port, reload=False)
        return

    service = ForgeService()
    if args.cmd == "index":
        repo = _repo_for_path(service, args.path)
        stats = service.index(repo["id"])
        print(json.dumps({"repo_id": repo["id"], "stats": stats}, indent=2))
        return

    if args.cmd == "run":
        load_config(args.config)
        repo = _repo_for_path(service, args.repo)
        if not repo.get("indexed_at"):
            service.index(repo["id"])
        override = {}
        if args.provider:
            override["provider"] = args.provider
        if args.model:
            override["model"] = args.model
        created = service.create_run(repo_id=repo["id"], config_name=args.config, goal=args.goal, llm_override=override)

        async def _go():
            queue = service.bus.subscribe(created["id"])
            task = asyncio.create_task(service.execute(created["id"]))
            while not task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.2)
                except TimeoutError:
                    continue
                payload = event.get("payload") or {}
                print(f"[{event.get('kind')}] {payload.get('message')}")
            await task
            service.bus.unsubscribe(created["id"], queue)

        asyncio.run(_go())
        finished = service.db.get_run(created["id"])
        print(json.dumps({"id": finished["id"], "status": finished["status"], "metrics": finished["metrics"]}, indent=2))
        return

    if args.cmd == "benchmark":
        repo = _repo_for_path(service, args.repo)
        service.index(repo["id"])
        configs = [item.strip() for item in args.configs.split(",") if item.strip()]
        task_ids = [item.strip() for item in args.tasks.split(",") if item.strip()] or None
        record = asyncio.run(
            run_benchmark(service, repo_id=repo["id"], config_names=configs, task_ids=task_ids)
        )
        print(format_table(record))
        print(f"\nwrote benchmarks/results/{record['id']}.json")


if __name__ == "__main__":
    main()
