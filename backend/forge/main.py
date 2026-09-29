"""FastAPI surface: repos, runs, configs, benchmarks, provider health, SSE."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from forge.benchmark.runner import run_benchmark
from forge.llm.providers import DEFAULTS, PROVIDER_NAMES, build_provider
from forge.service import ForgeService
from forge.settings import list_config_names, load_benchmark_tasks, load_config, save_config
from forge.studio import NotFound, StudioError
from forge import studio as studio_api

app = FastAPI(title="FORGE", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
service = ForgeService()


class RepoLocal(BaseModel):
    source: str = "local"
    path: str | None = None
    url: str | None = None
    token: str | None = None
    name: str | None = None


class RunCreate(BaseModel):
    repo_id: str
    config: str
    goal: str
    llm: dict[str, Any] | None = None


class ResumeBody(BaseModel):
    note: str = ""


class HealthBody(BaseModel):
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class BenchmarkBody(BaseModel):
    repo_id: str
    configs: list[str] = Field(default_factory=lambda: ["baseline", "planning", "planning_verify", "full_forge"])
    task_ids: list[str] | None = None
    llm: dict[str, Any] | None = None


class SkillBody(BaseModel):
    name: str
    description: str = ""
    body: str = ""
    enabled: bool = True


class SkillPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    body: str | None = None
    enabled: bool | None = None


class McpBody(BaseModel):
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    enabled: bool = False


class McpPatch(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    enabled: bool | None = None


def _studio_call(fn):
    try:
        return fn()
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except StudioError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "forge"}


@app.get("/api/configs")
def configs() -> list[dict[str, Any]]:
    return [load_config(name) for name in list_config_names()]


@app.get("/api/configs/{name}")
def config_one(name: str) -> dict[str, Any]:
    try:
        return load_config(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/api/configs/{name}")
def config_save(name: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return save_config(name, body)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/repos")
def repos() -> list[dict[str, Any]]:
    return service.db.list_repos()


@app.post("/api/repos")
def repos_create(body: RepoLocal) -> dict[str, Any]:
    try:
        if body.source == "github":
            if not body.url:
                raise HTTPException(400, "url is required for github")
            return service.connect_github(body.url, body.token, body.name)
        if not body.path:
            raise HTTPException(400, "path is required for a local repo")
        return service.connect_local(body.path, body.name)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/repos/{repo_id}")
def repo_one(repo_id: str) -> dict[str, Any]:
    repo = service.db.get_repo(repo_id)
    if not repo:
        raise HTTPException(404, "repo not found")
    return repo


@app.post("/api/repos/{repo_id}/index")
def repo_index(repo_id: str) -> dict[str, Any]:
    try:
        stats = service.index(repo_id)
    except KeyError as exc:
        raise HTTPException(404, "repo not found") from exc
    return {"repo": service.db.get_repo(repo_id), "stats": stats}


@app.get("/api/repos/{repo_id}/kg/search")
def repo_search(repo_id: str, q: str = "TodoStore") -> dict[str, Any]:
    from forge.kg.query import GraphRetriever

    if not service.db.get_repo(repo_id):
        raise HTTPException(404, "repo not found")
    retriever = GraphRetriever(service.db, repo_id)
    hits = retriever.search(q, limit=8)
    return {"query": q, "hits": hits, "pack": retriever.context_pack(q)}


@app.get("/api/repos/{repo_id}/kg/stats")
def repo_stats(repo_id: str) -> dict[str, Any]:
    repo = service.db.get_repo(repo_id)
    if not repo:
        raise HTTPException(404, "repo not found")
    return repo.get("kg_stats") or {}


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    return service.db.list_runs()


@app.post("/api/runs")
async def runs_create(body: RunCreate) -> dict[str, Any]:
    try:
        run = service.create_run(
            repo_id=body.repo_id,
            config_name=body.config,
            goal=body.goal,
            llm_override=body.llm,
        )
    except KeyError as exc:
        raise HTTPException(404, "repo not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    asyncio.create_task(service.execute(run["id"]))
    return run


@app.get("/api/runs/{run_id}")
def run_one(run_id: str) -> dict[str, Any]:
    run = service.db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


@app.post("/api/runs/{run_id}/resume")
def run_resume(run_id: str, body: ResumeBody) -> dict[str, Any]:
    try:
        return service.resume(run_id, body.note)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    if not service.db.get_run(run_id):
        raise HTTPException(404, "run not found")

    async def stream():
        queue = service.bus.subscribe(run_id)
        try:
            history = service.db.events_for(run_id)
            seen = set()
            for event in history:
                seen.add(event["id"])
                yield _sse(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=12)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    run = service.db.get_run(run_id)
                    if run and run["status"] in {"completed", "completed_with_failures", "failed"} and queue.empty():
                        break
                    continue
                if event.get("id") in seen:
                    continue
                seen.add(event.get("id"))
                yield _sse(event)
                if event.get("kind") == "status" and event.get("payload", {}).get("status") in {
                    "completed",
                    "completed_with_failures",
                    "failed",
                }:
                    break
        finally:
            service.bus.unsubscribe(run_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/providers")
def providers() -> list[dict[str, Any]]:
    rows = []
    for name in PROVIDER_NAMES:
        defaults = DEFAULTS[name]
        rows.append(
            {
                "provider": name,
                "model": defaults["model"],
                "base_url": defaults["base_url"],
                "api_key_env": defaults["api_key_env"],
            }
        )
    return rows


@app.post("/api/providers/health")
async def providers_health(body: HealthBody) -> dict[str, Any]:
    try:
        provider = build_provider(
            {"llm": {}},
            {
                "provider": body.provider,
                "model": body.model,
                "base_url": body.base_url,
                "api_key": body.api_key,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return {"provider": body.provider, "ok": False, "detail": str(exc)}
    return await provider.health()


@app.get("/api/benchmarks/tasks")
def benchmark_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": task["id"],
            "difficulty": task.get("difficulty"),
            "title": task.get("title"),
            "prompt": task.get("prompt"),
        }
        for task in load_benchmark_tasks()
    ]


@app.get("/api/benchmarks")
def benchmarks() -> list[dict[str, Any]]:
    return service.db.list_benchmarks()


@app.post("/api/benchmarks")
async def benchmarks_create(body: BenchmarkBody) -> dict[str, Any]:
    if not service.db.get_repo(body.repo_id):
        raise HTTPException(404, "repo not found")
    try:
        return await run_benchmark(
            service,
            repo_id=body.repo_id,
            config_names=body.configs,
            task_ids=body.task_ids,
            llm_override=body.llm,
        )
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/benchmarks/{bench_id}")
def benchmark_one(bench_id: str) -> dict[str, Any]:
    record = service.db.get_benchmark(bench_id)
    if not record:
        raise HTTPException(404, "benchmark not found")
    return record


@app.get("/api/benchmarks/{bench_id}/export.csv")
def benchmark_csv(bench_id: str):
    from forge.benchmark.runner import format_table
    from forge.settings import ROOT

    record = service.db.get_benchmark(bench_id)
    if not record:
        raise HTTPException(404, "benchmark not found")
    path = ROOT / "benchmarks" / "results" / f"{bench_id}.csv"
    if path.exists():
        return PlainTextResponse(path.read_text(), media_type="text/csv")
    return PlainTextResponse(format_table(record), media_type="text/plain")


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/api/studio")
def studio_snapshot(config: str = "full_forge") -> dict[str, Any]:
    return _studio_call(lambda: studio_api.snapshot(service.db, config))


@app.post("/api/skills")
def skill_create(body: SkillBody) -> dict[str, Any]:
    return _studio_call(
        lambda: studio_api.create_skill(
            service.db,
            name=body.name,
            description=body.description,
            body=body.body,
            enabled=body.enabled,
        )
    )


@app.put("/api/skills/{skill_id}")
def skill_update(skill_id: str, body: SkillPatch) -> dict[str, Any]:
    return _studio_call(lambda: studio_api.update_skill(service.db, skill_id, body.model_dump(exclude_unset=True)))


@app.delete("/api/skills/{skill_id}")
def skill_delete(skill_id: str) -> dict[str, bool]:
    _studio_call(lambda: studio_api.delete_skill(service.db, skill_id))
    return {"ok": True}


@app.post("/api/mcp")
def mcp_create(body: McpBody) -> dict[str, Any]:
    return _studio_call(
        lambda: studio_api.create_mcp(
            service.db,
            name=body.name,
            transport=body.transport,
            command=body.command,
            args=body.args,
            url=body.url,
            enabled=body.enabled,
        )
    )


@app.put("/api/mcp/{server_id}")
def mcp_update(server_id: str, body: McpPatch) -> dict[str, Any]:
    return _studio_call(lambda: studio_api.update_mcp(service.db, server_id, body.model_dump(exclude_unset=True)))


@app.delete("/api/mcp/{server_id}")
def mcp_delete(server_id: str) -> dict[str, bool]:
    _studio_call(lambda: studio_api.delete_mcp(service.db, server_id))
    return {"ok": True}


@app.post("/api/mcp/{server_id}/probe")
def mcp_probe(server_id: str) -> dict[str, Any]:
    return _studio_call(lambda: studio_api.probe_mcp(service.db, server_id))


@app.post("/api/mcp/demo")
def mcp_demo() -> dict[str, Any]:
    return _studio_call(lambda: studio_api.install_demo(service.db))
