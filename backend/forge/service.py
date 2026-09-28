"""Connect a repo, index it, and run the harness."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

from forge.core import checkpoints
from forge.core.executor import execute_task
from forge.core.planner import create_plan
from forge.core.recovery import decide_strategy
from forge.core.verifier import verify_task
from forge.db import Database
from forge.events import EventBus
from forge.kg.indexer import index_repo
from forge.kg.query import GraphRetriever
from forge.llm.providers import build_provider
from forge.settings import flag, load_config
from forge.util import new_id, redact, utc_now


class ForgeService:
    def __init__(
        self,
        db: Database | None = None,
        bus: EventBus | None = None,
        workspace_root: Path | None = None,
    ):
        self.db = db or Database()
        self.bus = bus or EventBus()
        self.workspace_root = workspace_root
        self._resume: dict[str, asyncio.Event] = {}
        self._notes: dict[str, str] = {}
        self._interactive: dict[str, bool] = {}

    # --- repos ---
    def connect_local(self, path: str, name: str | None = None) -> dict[str, Any]:
        folder = Path(path).expanduser().resolve()
        if not folder.is_dir():
            raise FileNotFoundError(f"not a directory: {folder}")
        repo = {
            "id": new_id("repo"),
            "name": name or folder.name,
            "source": "local",
            "path": str(folder),
            "url": "",
            "token": "",
            "indexed_at": None,
            "kg_stats": None,
            "created_at": utc_now(),
        }
        self.db.insert_repo(repo)
        return self.db.get_repo(repo["id"])

    def connect_github(self, url: str, token: str | None = None, name: str | None = None) -> dict[str, Any]:
        from forge.settings import DATA_DIR

        repo_id = new_id("repo")
        dest = DATA_DIR / "clones" / repo_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        clone_url = _authed(url, token)
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(dest)],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            message = redact((proc.stderr or proc.stdout or "git clone failed"), token)
            raise RuntimeError(message.strip())
        guessed = url.rstrip("/").split("/")[-1].removesuffix(".git")
        repo = {
            "id": repo_id,
            "name": name or guessed,
            "source": "github",
            "path": str(dest),
            "url": url,
            "token": token or "",
            "indexed_at": None,
            "kg_stats": None,
            "created_at": utc_now(),
        }
        self.db.insert_repo(repo)
        return self.db.get_repo(repo_id)

    def index(self, repo_id: str) -> dict[str, Any]:
        repo = self.db.get_repo_raw(repo_id)
        if not repo:
            raise KeyError(repo_id)
        stats = index_repo(self.db, repo_id, Path(repo["path"]))
        self.db.update_repo_index(repo_id, stats)
        return stats

    # --- runs ---
    def create_run(
        self,
        *,
        repo_id: str,
        config_name: str,
        goal: str,
        llm_override: dict[str, Any] | None = None,
        interactive: bool = True,
    ) -> dict[str, Any]:
        if not self.db.get_repo_raw(repo_id):
            raise KeyError(repo_id)
        load_config(config_name)
        run_id = new_id("run")
        self._interactive[run_id] = interactive
        self.db.insert_run(
            {
                "id": run_id,
                "repo_id": repo_id,
                "config_name": config_name,
                "goal": goal,
                "status": "queued",
                "workspace": "",
                "branch": "",
                "started_at": utc_now(),
                "ended_at": None,
                "metrics": {},
                "error": "",
                "human_question": "",
                "plan": {},
                "llm_override": llm_override or {},
            }
        )
        return self.db.get_run(run_id)

    def resume(self, run_id: str, note: str) -> dict[str, Any]:
        self._notes[run_id] = note
        event = self._resume.get(run_id)
        if event is None:
            raise RuntimeError("this run is not waiting for a person")
        event.set()
        return self.db.get_run(run_id)

    async def execute(self, run_id: str) -> dict[str, Any]:
        try:
            await self._execute(run_id)
        except Exception as exc:  # noqa: BLE001 — surface harness crashes on the run
            self.db.update_run(run_id, status="failed", error=str(exc), ended_at=utc_now())
            self._emit(run_id, "status", f"run failed: {exc}", status="failed")
        return self.db.get_run(run_id)

    async def _execute(self, run_id: str) -> None:
        run = self.db.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        cfg = load_config(run["config_name"])
        repo = self.db.get_repo_raw(run["repo_id"])
        workspace = self._make_workspace(Path(repo["path"]), run_id)
        self.db.update_run(run_id, workspace=str(workspace), status="planning")
        self._emit(run_id, "status", "preparing workspace", status="planning", workspace=str(workspace))

        llm = build_provider(cfg, run.get("llm") or {})
        retriever = None
        if flag(cfg, "kg_retrieval") or flag(cfg, "context_packs") or flag(cfg, "graph_rag"):
            if not repo.get("indexed_at"):
                self.index(run["repo_id"])
            retriever = GraphRetriever(self.db, run["repo_id"])
        original_tests = _original_tests(workspace)
        branch = ""
        if flag(cfg, "git_checkpoints"):
            branch = checkpoints.start_branch(workspace, run_id)
            checkpoints.mark_base(workspace)
            self.db.update_run(run_id, branch=branch)
            self._emit(run_id, "log", f"git branch {branch}", branch=branch)

        summary = retriever.summary() if retriever else ""
        hints = retriever.file_hints() if retriever else []
        plan, plan_call = await create_plan(
            run["goal"],
            planning=flag(cfg, "planning"),
            llm=llm,
            repo_summary=summary,
            file_hints=hints,
        )
        if plan_call:
            self._record_llm(run_id, None, plan_call)
        self.db.update_run(run_id, plan=plan, status="running")
        tasks = self._persist_plan(run_id, plan)
        self._emit(run_id, "log", plan.get("summary") or "plan ready", tasks=len(tasks))

        state = {task["task_key"]: task for task in tasks}
        recovery_on = flag(cfg, "recovery")
        verify_on = flag(cfg, "verification")
        checks_passed = 0
        checks_total = 0
        asked = False
        replans = 0

        while True:
            task = _next_ready(list(state.values()), recovery_on)
            if task is None:
                for pending in state.values():
                    if pending["status"] == "blocked":
                        self.db.update_task(pending["id"], status="blocked", summary="blocked by an unfinished dependency")
                break
            outcome = await self._run_task(
                run=run,
                cfg=cfg,
                llm=llm,
                workspace=workspace,
                task=task,
                retriever=retriever,
                original_tests=original_tests,
                verify_on=verify_on,
                recovery_on=recovery_on,
                replans=replans,
            )
            replans = outcome["replans"]
            checks_passed += outcome["checks_passed"]
            checks_total += outcome["checks_total"]
            asked = asked or outcome["asked"]
            state[task["task_key"]] = self._reload_task(run_id, task["id"])

        final_tasks = self.db.tasks_for(run_id)
        failed = [task for task in final_tasks if task["status"] == "failed"]
        if asked and any(task["status"] == "awaiting_human" for task in final_tasks):
            status = "awaiting_human"
        elif recovery_on and failed:
            status = "failed"
        elif failed:
            status = "completed_with_failures"
        else:
            status = "completed"
        metrics = self._metrics(run_id, checks_passed, checks_total, asked)
        self.db.update_run(run_id, status=status, ended_at=utc_now(), metrics=metrics, branch=branch)
        self._emit(run_id, "status", f"run {status}", status=status, metrics=metrics)

    async def _run_task(
        self,
        *,
        run: dict[str, Any],
        cfg: dict[str, Any],
        llm,
        workspace: Path,
        task: dict[str, Any],
        retriever,
        original_tests: list[str],
        verify_on: bool,
        recovery_on: bool,
        replans: int,
    ) -> dict[str, Any]:
        recovery_cfg = cfg.get("recovery") or {}
        max_retries = int(recovery_cfg.get("max_retries") or 0)
        max_attempts = max_retries + 1 if recovery_on else 1
        diagnosis = None
        checks_passed = 0
        checks_total = 0
        asked = False
        attempt = 0
        pre_rev = None
        while attempt < max_attempts:
            attempt += 1
            started = asyncio.get_event_loop().time()
            self.db.update_task(task["id"], status="running", attempt=attempt, started_at=utc_now())
            self._emit(run["id"], "task", f"{task['task_key']} attempt {attempt}", task_key=task["task_key"], status="running", attempt=attempt)
            if flag(cfg, "git_checkpoints"):
                pre_rev = checkpoints.snapshot(workspace, f"{task['task_key']} attempt {attempt} before")
            memory = self.db.recent_failures(run["repo_id"]) if flag(cfg, "failure_memory") else []
            changed: list[str] = []

            async def on_llm(response, prompt: str, phase: str, task_id=task["id"]):
                self._record_llm(
                    run["id"],
                    task_id,
                    {
                        "phase": phase,
                        "provider": response.provider,
                        "model": response.model,
                        "prompt_preview": prompt[:800],
                        "response_preview": response.text[:1500],
                        "tokens_in": response.prompt_tokens,
                        "tokens_out": response.completion_tokens,
                        "latency_ms": int(response.latency_ms),
                    },
                )

            async def on_tool(name, args, ok, result, elapsed, task_id=task["id"]):
                preview_args = {key: value for key, value in dict(args).items() if key != "content"}
                if "content" in args:
                    preview_args["content_lines"] = len(str(args.get("content") or "").splitlines())
                self.db.add_tool_call(
                    {
                        "id": new_id("tool"),
                        "run_id": run["id"],
                        "task_id": task_id,
                        "name": name,
                        "args": preview_args,
                        "result_preview": (result or "")[:800],
                        "ok": 1 if ok else 0,
                        "elapsed_ms": elapsed,
                        "created_at": utc_now(),
                    }
                )
                self._emit(run["id"], "tool", f"{name} {'ok' if ok else 'error'}", tool=name, ok=ok, task_key=task["task_key"])
                if name == "write_file" and ok:
                    changed.append(str(args.get("path")))

            result = await execute_task(
                llm=llm,
                cfg=cfg,
                workspace=workspace,
                goal=run["goal"],
                task=task,
                attempt=attempt,
                diagnosis=diagnosis,
                retriever=retriever,
                failure_memory=memory,
                on_llm=on_llm,
                on_tool=on_tool,
            )
            elapsed_ms = int((asyncio.get_event_loop().time() - started) * 1000)
            if not verify_on:
                self.db.update_task(
                    task["id"],
                    status="done",
                    ended_at=utc_now(),
                    elapsed_ms=elapsed_ms,
                    summary=result.get("summary") or "",
                )
                self._emit(run["id"], "task", f"{task['task_key']} done (verification off)", task_key=task["task_key"], status="done")
                return {"checks_passed": 0, "checks_total": 0, "asked": asked, "replans": replans}

            self._emit(run["id"], "log", f"verifying {task['task_key']}", task_key=task["task_key"])
            levels = list((cfg.get("verification") or {}).get("levels") or [])
            report = await verify_task(
                workspace=workspace,
                levels=levels,
                fail_fast=bool((cfg.get("verification") or {}).get("fail_fast", True)),
                expected_output=task.get("expected_output") or "",
                changed=changed,
                original_tests=original_tests,
                llm=llm,
                attempt=attempt,
            )
            if report["diagnosis"] and report["diagnosis"].get("llm"):
                info = report["diagnosis"]["llm"]
                self._record_llm(run["id"], task["id"], {**info, "phase": "diagnose"})
            passed = sum(1 for check in report["checks"] if check["ok"])
            total = len(report["checks"])
            # Headline pass rate uses the final attempt only. Earlier misses stay in the log.
            checks_passed = passed
            checks_total = total
            for check in report["checks"]:
                self._emit(
                    run["id"],
                    "log",
                    f"{check['level']}: {'pass' if check['ok'] else 'fail'}",
                    level=check["level"],
                    ok=check["ok"],
                    task_key=task["task_key"],
                )
            if report["ok"]:
                if flag(cfg, "git_checkpoints"):
                    checkpoints.commit_success(workspace, f"forge: {task['title']}")
                self.db.resolve_failures(run["id"], task["task_key"])
                self.db.update_task(
                    task["id"],
                    status="done",
                    ended_at=utc_now(),
                    elapsed_ms=elapsed_ms,
                    summary=result.get("summary") or "",
                )
                self._emit(run["id"], "task", f"{task['task_key']} verified", task_key=task["task_key"], status="done")
                return {"checks_passed": checks_passed, "checks_total": checks_total, "asked": asked, "replans": replans}

            diagnosis = report["diagnosis"] or {}
            if not recovery_on:
                self.db.add_failure(
                    {
                        "id": new_id("fail"),
                        "run_id": run["id"],
                        "repo_id": run["repo_id"],
                        "task_key": task["task_key"],
                        "failure_class": diagnosis.get("failure_class") or "code_bug",
                        "evidence": (diagnosis.get("evidence") or "")[:1500],
                        "strategy": "none",
                        "attempt": attempt,
                        "resolved": 0,
                        "risk": float(diagnosis.get("risk") or 0),
                        "created_at": utc_now(),
                    }
                )
                self.db.update_task(task["id"], status="failed", ended_at=utc_now(), elapsed_ms=elapsed_ms, summary=diagnosis.get("why") or "verification failed")
                self._emit(run["id"], "failure", diagnosis.get("why") or "verification failed", task_key=task["task_key"], failure_class=diagnosis.get("failure_class"))
                return {"checks_passed": checks_passed, "checks_total": checks_total, "asked": asked, "replans": replans}

            strategy = decide_strategy(
                failure_class=diagnosis.get("failure_class") or "code_bug",
                risk=float(diagnosis.get("risk") or 0.4),
                attempt=attempt,
                max_retries=max_retries,
                risk_threshold=float(recovery_cfg.get("risk_threshold") or 0.72),
                strategies=list(recovery_cfg.get("strategies") or []),
            )
            self.db.add_failure(
                {
                    "id": new_id("fail"),
                    "run_id": run["id"],
                    "repo_id": run["repo_id"],
                    "task_key": task["task_key"],
                    "failure_class": diagnosis.get("failure_class") or "code_bug",
                    "evidence": (diagnosis.get("evidence") or "")[:1500],
                    "strategy": strategy,
                    "attempt": attempt,
                    "resolved": 0,
                    "risk": float(diagnosis.get("risk") or 0),
                    "created_at": utc_now(),
                }
            )
            self._emit(
                run["id"],
                "failure",
                f"{diagnosis.get('failure_class')} → {strategy}",
                task_key=task["task_key"],
                failure_class=diagnosis.get("failure_class"),
                strategy=strategy,
            )
            if strategy == "retry":
                continue
            if strategy == "rollback" and pre_rev and flag(cfg, "git_checkpoints"):
                checkpoints.rollback(workspace, pre_rev)
                self._emit(run["id"], "log", f"rolled back {task['task_key']}", task_key=task["task_key"])
                continue
            if strategy == "replan":
                replans += 1
                if replans > 2:
                    break
                revised = run["goal"] + "\n\nThe previous attempt failed.\n" + (diagnosis.get("why") or "")
                plan, plan_call = await create_plan(
                    revised,
                    planning=True,
                    llm=llm,
                    repo_summary="",
                    file_hints=task.get("files_hint") if isinstance(task.get("files_hint"), list) else [],
                )
                if plan_call:
                    self._record_llm(run["id"], task["id"], plan_call)
                self._append_new_tasks(run["id"], plan)
                self._emit(run["id"], "log", "replanned remaining work", task_key=task["task_key"])
                continue
            if strategy == "ask_human":
                asked = True
                question = diagnosis.get("why") or "Verification failed and the risk threshold says to ask."
                if not self._interactive.get(run["id"], True):
                    self.db.update_task(
                        task["id"],
                        status="failed",
                        ended_at=utc_now(),
                        summary="recovery asked for a human; this run is non-interactive",
                    )
                    self._emit(run["id"], "failure", "ask_human (non-interactive)", task_key=task["task_key"], strategy="ask_human")
                    return {"checks_passed": checks_passed, "checks_total": checks_total, "asked": asked, "replans": replans}
                self.db.update_run(run["id"], status="awaiting_human", human_question=question)
                self.db.update_task(task["id"], status="awaiting_human")
                self._emit(run["id"], "status", question, status="awaiting_human", task_key=task["task_key"])
                note = await self._wait_for_human(run["id"])
                diagnosis = {
                    **diagnosis,
                    "evidence": (diagnosis.get("evidence") or "") + "\nHUMAN:\n" + note,
                    "why": note or diagnosis.get("why"),
                }
                self.db.update_run(run["id"], status="running", human_question="")
                continue
            # isolate, or a strategy we cannot apply
            self.db.update_task(task["id"], status="skipped", ended_at=utc_now(), summary=f"isolated after {strategy}")
            self._emit(run["id"], "task", f"{task['task_key']} isolated", task_key=task["task_key"], status="skipped")
            return {"checks_passed": checks_passed, "checks_total": checks_total, "asked": asked, "replans": replans}

        self.db.update_task(task["id"], status="failed", ended_at=utc_now(), summary="recovery budget exhausted")
        self._emit(run["id"], "task", f"{task['task_key']} failed", task_key=task["task_key"], status="failed")
        return {"checks_passed": checks_passed, "checks_total": checks_total, "asked": asked, "replans": replans}

    async def _wait_for_human(self, run_id: str) -> str:
        event = asyncio.Event()
        self._resume[run_id] = event
        await event.wait()
        self._resume.pop(run_id, None)
        return self._notes.pop(run_id, "")

    def _append_new_tasks(self, run_id: str, plan: dict[str, Any]) -> None:
        existing = self.db.tasks_for(run_id)
        titles = {task["title"] for task in existing}
        phase_of = _phase_map(plan)
        for task in plan.get("tasks") or []:
            if task["title"] in titles:
                continue
            self.db.insert_task(_task_row(run_id, task, phase_of.get(task["id"], "")))

    def _persist_plan(self, run_id: str, plan: dict[str, Any]) -> list[dict[str, Any]]:
        phase_of = _phase_map(plan)
        rows = [_task_row(run_id, task, phase_of.get(task["id"], "")) for task in plan["tasks"]]
        self.db.replace_tasks(run_id, rows)
        return self.db.tasks_for(run_id)

    def _reload_task(self, run_id: str, task_id: str) -> dict[str, Any]:
        for task in self.db.tasks_for(run_id):
            if task["id"] == task_id:
                return task
        raise KeyError(task_id)

    def _record_llm(self, run_id: str, task_id: str | None, info: dict[str, Any]) -> None:
        self.db.add_llm_call(
            {
                "id": new_id("llm"),
                "run_id": run_id,
                "task_id": task_id,
                "provider": info.get("provider"),
                "model": info.get("model"),
                "phase": info.get("phase"),
                "prompt_preview": info.get("prompt_preview") or "",
                "response_preview": info.get("response_preview") or "",
                "tokens_in": int(info.get("tokens_in") or 0),
                "tokens_out": int(info.get("tokens_out") or 0),
                "latency_ms": int(info.get("latency_ms") or 0),
                "created_at": utc_now(),
            }
        )
        self._emit(
            run_id,
            "llm",
            f"{info.get('phase')} {info.get('provider')}/{info.get('model')}",
            phase=info.get("phase"),
            tokens_in=info.get("tokens_in"),
            tokens_out=info.get("tokens_out"),
            latency_ms=info.get("latency_ms"),
        )

    def _metrics(self, run_id: str, checks_passed: int, checks_total: int, asked: bool) -> dict[str, Any]:
        run = self.db.get_run(run_id)
        tokens_in = sum(int(call.get("tokens_in") or 0) for call in run["llm_calls"])
        tokens_out = sum(int(call.get("tokens_out") or 0) for call in run["llm_calls"])
        failures = run["failures"]
        resolved = sum(1 for item in failures if item.get("resolved"))
        tasks = run["tasks"]
        started = run.get("started_at")
        ended = utc_now()
        return {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens": tokens_in + tokens_out,
            "llm_calls": len(run["llm_calls"]),
            "tool_calls": len(run["tool_calls"]),
            "elapsed_ms": _elapsed_ms(started, ended),
            "verification_pass_rate": (checks_passed / checks_total) if checks_total else None,
            "recovery_success": (resolved / len(failures)) if failures else None,
            "human_intervention": asked,
            "tasks_total": len(tasks),
            "tasks_done": sum(1 for task in tasks if task["status"] == "done"),
            "tasks_failed": sum(1 for task in tasks if task["status"] == "failed"),
            "checks_passed": checks_passed,
            "checks_total": checks_total,
            "failures": len(failures),
            "failures_resolved": resolved,
        }

    def _make_workspace(self, source: Path, run_id: str) -> Path:
        from forge.settings import DATA_DIR

        base = self.workspace_root or DATA_DIR
        dest = base / "workspaces" / run_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            source,
            dest,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc", ".venv"),
        )
        # Keep pytest from walking up into the FORGE backend config.
        (dest / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
        return dest

    def _emit(self, run_id: str, kind: str, message: str, **data: Any) -> None:
        payload = {"message": message, **data}
        event = self.db.add_event(run_id, kind, payload)
        row = self.db.one("SELECT id, created_at FROM events WHERE run_id = ? ORDER BY id DESC LIMIT 1", (run_id,))
        if row:
            event = {"id": row["id"], "run_id": run_id, "kind": kind, "payload": payload, "created_at": row["created_at"]}
        self.bus.publish(run_id, event)


def _task_row(run_id: str, task: dict[str, Any], phase: str) -> dict[str, Any]:
    return {
        "id": new_id("task"),
        "run_id": run_id,
        "task_key": task["id"],
        "title": task.get("title") or task["id"],
        "description": task.get("description") or "",
        "dependencies": task.get("dependencies") or [],
        "expected_output": task.get("expected_output") or "",
        "failure_conditions": task.get("failure_conditions") or [],
        "phase": phase,
        "status": "pending",
        "attempt": 0,
        "started_at": None,
        "ended_at": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "elapsed_ms": 0,
        "summary": "",
    }


def _phase_map(plan: dict[str, Any]) -> dict[str, str]:
    mapping = {}
    for phase in plan.get("phases") or []:
        for task_id in phase.get("task_ids") or []:
            mapping[task_id] = phase.get("id") or ""
    return mapping


def _next_ready(tasks: list[dict[str, Any]], recovery_on: bool) -> dict[str, Any] | None:
    by_key = {task["task_key"]: task for task in tasks}
    allowed = {"done"} if recovery_on else {"done", "failed", "skipped", "blocked"}
    for task in tasks:
        if task["status"] != "pending":
            continue
        deps = task.get("dependencies") or []
        if all(by_key.get(dep, {}).get("status") in allowed for dep in deps):
            return task
    for task in tasks:
        if task["status"] == "pending":
            task["status"] = "blocked"
    return None


def _original_tests(workspace: Path) -> list[str]:
    folder = workspace / "tests"
    if not folder.exists():
        return []
    return [
        str(path.relative_to(workspace))
        for path in sorted(folder.glob("test_*.py"))
        if path.name != "test_requested.py"
    ]


def _elapsed_ms(started: str | None, ended: str | None) -> int:
    from datetime import datetime

    if not started or not ended:
        return 0
    try:
        a = datetime.fromisoformat(started)
        b = datetime.fromisoformat(ended)
    except ValueError:
        return 0
    return max(0, int((b - a).total_seconds() * 1000))


def _authed(url: str, token: str | None) -> str:
    if not token or "github.com/" not in url:
        return url
    if url.startswith("https://github.com/"):
        suffix = url[len("https://github.com/") :]
        return f"https://x-access-token:{token}@github.com/{suffix}"
    return url
