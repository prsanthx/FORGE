import { useEffect, useState } from "react";
import { api } from "../api";
import Dag from "../components/Dag";
import { elapsedSince, fmtMs, fmtRate, statusTone } from "../format";
import type { Run, RunEvent } from "../types";

export default function RunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [note, setNote] = useState("Please fix the failing check and keep existing tests passing.");
  const [error, setError] = useState("");
  const [, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.run(id).then((row) => {
      if (!cancelled) setRun(row);
    }).catch((err: Error) => setError(err.message));
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000);
    const source = new EventSource(`/api/runs/${id}/events`);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent;
      setEvents((current) => (current.some((item) => item.id === event.id) ? current : [...current, event]));
      if (event.kind === "status" || event.kind === "task" || event.kind === "failure") {
        api.run(id).then(setRun).catch(() => undefined);
      }
    };
    source.onerror = () => {
      api.run(id).then(setRun).catch(() => undefined);
    };
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      source.close();
    };
  }, [id]);

  if (!run) return <p className="text-mute">{error || "Loading run…"}</p>;
  const live = ["queued", "planning", "running", "awaiting_human"].includes(run.status);
  const elapsed = live ? elapsedSince(run.started_at) : run.metrics?.elapsed_ms || elapsedSince(run.started_at, run.ended_at);
  const calls = run.llm_calls || [];
  const byTask = new Map<string, { inn: number; out: number }>();
  for (const call of calls) {
    const key = call.task_id || "plan";
    const row = byTask.get(key) || { inn: 0, out: 0 };
    row.inn += call.tokens_in || 0;
    row.out += call.tokens_out || 0;
    byTask.set(key, row);
  }

  return (
    <div className="space-y-5">
      <header className="flex items-start justify-between gap-4">
        <div>
          <div className="kicker">Run {run.id}</div>
          <h1 className="mt-1 max-w-4xl font-display text-3xl">{run.goal}</h1>
          <p className="mt-2 text-sm text-mute">
            {run.config_name}
            {run.branch ? ` · ${run.branch}` : ""} {run.workspace ? `· ${run.workspace}` : ""}
          </p>
        </div>
        <span className={`rounded border px-3 py-1 text-sm ${statusTone(run.status)}`}>{run.status}</span>
      </header>
      <section className="grid grid-cols-4 gap-3">
        {[
          ["Elapsed", fmtMs(elapsed)],
          ["Tokens", String(run.metrics?.tokens ?? calls.reduce((sum, call) => sum + call.tokens_in + call.tokens_out, 0))],
          ["Verification", fmtRate(run.metrics?.verification_pass_rate)],
          ["Recovery", fmtRate(run.metrics?.recovery_success)],
        ].map(([label, value]) => (
          <div key={label} className="panel px-4 py-3">
            <div className="kicker">{label}</div>
            <div className="mt-1 text-2xl">{value}</div>
          </div>
        ))}
      </section>
      {run.plan?.summary && <p className="text-sm text-mute">{run.plan.summary}</p>}
      {run.error && <p className="text-sm text-bad">{run.error}</p>}
      {run.status === "awaiting_human" && (
        <section className="panel border-info/40 p-4">
          <div className="kicker">Ask human</div>
          <p className="mt-2 text-sm">{run.human_question}</p>
          <textarea className="mt-3 h-20 w-full rounded border border-line bg-black/30 p-2 text-sm" value={note} onChange={(event) => setNote(event.target.value)} />
          <button
            className="mt-2 rounded bg-info px-3 py-1.5 text-sm text-black"
            onClick={() => api.resume(id, note).then(() => api.run(id).then(setRun)).catch((err: Error) => setError(err.message))}
          >
            Resume with this note
          </button>
        </section>
      )}
      <section className="panel p-4">
        <div className="kicker">Task graph</div>
        <div className="mt-3">
          <Dag tasks={run.tasks || []} />
        </div>
      </section>
      <section className="grid grid-cols-[1.1fr_0.9fr] gap-4">
        <div className="panel p-4">
          <div className="kicker">Developer log</div>
          <div className="mt-3 h-80 overflow-auto rounded bg-black/40 p-3 font-mono text-xs leading-5">
            {events.map((event) => (
              <div key={event.id}>
                <span className="text-brass">{event.kind.padEnd(8, " ")}</span>
                <span className="text-ink/90">{event.payload.message}</span>
              </div>
            ))}
            {events.length === 0 && <div className="text-mute">Waiting for events…</div>}
          </div>
        </div>
        <div className="panel p-4">
          <div className="kicker">LLM calls</div>
          <div className="mt-3 max-h-80 space-y-2 overflow-auto">
            {calls.map((call) => (
              <details key={call.id} className="rounded border border-line px-3 py-2 text-sm">
                <summary className="cursor-pointer">
                  {call.phase} · {call.provider}/{call.model} · {call.tokens_in + call.tokens_out} tok · {call.latency_ms}ms
                </summary>
                <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] text-mute">{call.response_preview}</pre>
              </details>
            ))}
            {calls.length === 0 && <p className="text-sm text-mute">No model calls yet.</p>}
          </div>
        </div>
      </section>
      <section className="panel p-4">
        <div className="kicker">Tokens by task</div>
        <div className="mt-3 space-y-2">
          {[...(run.tasks || [])].map((task) => {
            const row = byTask.get(task.id) || { inn: 0, out: 0 };
            const total = row.inn + row.out;
            const width = Math.min(100, total / 20);
            return (
              <div key={task.id} className="grid grid-cols-[180px_1fr_80px] items-center gap-3 text-sm">
                <div className="truncate text-mute">{task.task_key}</div>
                <div className="h-2 rounded bg-black/40">
                  <div className="h-2 rounded bg-brass" style={{ width: `${width}%` }} />
                </div>
                <div className="text-right font-mono text-xs">{total}</div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
