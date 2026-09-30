import { useEffect, useState } from "react";
import { api } from "../api";
import Dag from "../components/Dag";
import { elapsedSince, fmtMs, fmtRate, isLive, statusTone } from "../format";
import type { Run, RunEvent } from "../types";

type Tab = "log" | "model" | "tools" | "failures";

export default function RunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [note, setNote] = useState("Please fix the failing check and keep existing tests passing.");
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("log");
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

  if (!run) {
    return (
      <div className="space-y-3">
        <div className="skeleton h-8 w-2/3 rounded-lg" />
        <div className="grid grid-cols-4 gap-3">
          <div className="skeleton h-20 rounded-xl" />
          <div className="skeleton h-20 rounded-xl" />
          <div className="skeleton h-20 rounded-xl" />
          <div className="skeleton h-20 rounded-xl" />
        </div>
        <p className="text-sm text-mute">{error || "Loading run"}</p>
      </div>
    );
  }

  const live = isLive(run.status);
  const elapsed = live ? elapsedSince(run.started_at) : run.metrics?.elapsed_ms || elapsedSince(run.started_at, run.ended_at);
  const calls = run.llm_calls || [];
  const tools = run.tool_calls || [];
  const failures = run.failures || [];
  const byTask = new Map<string, { inn: number; out: number }>();
  for (const call of calls) {
    const key = call.task_id || "plan";
    const row = byTask.get(key) || { inn: 0, out: 0 };
    row.inn += call.tokens_in || 0;
    row.out += call.tokens_out || 0;
    byTask.set(key, row);
  }
  const tokenTotal = run.metrics?.tokens ?? calls.reduce((sum, call) => sum + call.tokens_in + call.tokens_out, 0);
  const verify = run.metrics?.verification_pass_rate;
  const maxTokens = Math.max(1, ...[...(run.tasks || [])].map((task) => {
    const row = byTask.get(task.id) || { inn: 0, out: 0 };
    return row.inn + row.out;
  }));

  return (
    <div className="stagger space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <a href="#/" className="kicker hover:text-ink">← Sessions</a>
          <h1 className="mt-2 max-w-4xl text-[22px] font-semibold leading-snug tracking-tight">{run.goal}</h1>
          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-faint">
            <span>{run.id}</span>
            <span>{run.config_name}</span>
            {run.branch && <span>{run.branch}</span>}
          </p>
        </div>
        <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[12px] ${statusTone(run.status)}`}>
          <span className={`status-dot ${live ? "is-live" : ""}`} />
          {run.status.replaceAll("_", " ")}
        </span>
      </header>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Elapsed" value={fmtMs(elapsed)} hint={live ? "Still running" : "Finished"} />
        <Metric label="Tokens" value={tokenTotal.toLocaleString()} hint={`${calls.length} model calls`} />
        <Metric label="Verification" value={fmtRate(verify)} hint="Final funnel" meter={typeof verify === "number" ? verify : undefined} />
        <Metric label="Recovery" value={fmtRate(run.metrics?.recovery_success)} hint={failures.length ? `${failures.length} failures` : "No failures"} />
      </section>

      {run.plan?.phases && run.plan.phases.length > 0 && (
        <section className="panel flex gap-2 overflow-x-auto p-3">
          {run.plan.phases.map((phase, index) => (
            <div key={phase.id} className="flex min-w-[140px] items-center gap-2 rounded-lg bg-elevated px-3 py-2">
              <span className="font-mono text-[11px] text-faint">{String(index + 1).padStart(2, "0")}</span>
              <span className="text-[13px]">{phase.title}</span>
            </div>
          ))}
        </section>
      )}
      {run.plan?.summary && <p className="text-[13px] leading-6 text-mute">{run.plan.summary}</p>}
      {run.error && <p className="rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">{run.error}</p>}

      {run.status === "awaiting_human" && (
        <section className="panel border-info/30 p-4">
          <div className="kicker">Needs a person</div>
          <p className="mt-2 text-sm">{run.human_question}</p>
          <textarea className="field mt-3 h-20" value={note} onChange={(event) => setNote(event.target.value)} />
          <button
            className="btn-primary mt-3"
            onClick={() => api.resume(id, note).then(() => api.run(id).then(setRun)).catch((err: Error) => setError(err.message))}
          >
            Resume
          </button>
        </section>
      )}

      <section className="panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-[13px] font-medium">Task graph</div>
          <div className="text-[11px] text-faint">{run.tasks?.length || 0} tasks</div>
        </div>
        <Dag tasks={run.tasks || []} />
      </section>

      <section className="panel p-4">
        <div className="text-[13px] font-medium">Transcript</div>
        <div className="mt-3 space-y-3">
          <div className="bubble-user px-3 py-2.5">
            <div className="text-[10px] font-medium uppercase tracking-wider text-faint">You</div>
            <p className="mt-1 whitespace-pre-wrap text-[13px] leading-6">{run.goal}</p>
          </div>
          {transcript(calls, tools).map((step) =>
            step.kind === "model" ? (
              <div key={step.id} className="bubble-step px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="chip">Model</span>
                  <span className="font-mono text-[12px]">{step.phase}</span>
                  <span className="text-[11px] text-faint">{step.provider}/{step.model}</span>
                </div>
                <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-5 text-mute">{step.response || "No response text."}</pre>
              </div>
            ) : (
              <div key={step.id} className="bubble-step px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="chip chip-on">{toolLabel(step.name)}</span>
                  <span className={`chip ${step.ok ? "text-ok" : "text-bad"}`}>{step.ok ? "ok" : "failed"}</span>
                  <span className="font-mono text-[11px] text-faint">{step.elapsed}ms</span>
                </div>
                {step.args && <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-5 text-faint">{step.args}</pre>}
                {step.result && <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] leading-5 text-mute">{step.result}</pre>}
              </div>
            ),
          )}
          {calls.length + tools.length === 0 && <p className="text-sm text-mute">Steps appear after the model starts.</p>}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-1">
            {(["log", "model", "tools", "failures"] as Tab[]).map((item) => (
              <button
                key={item}
                className={`rounded-md px-2.5 py-1 text-[12px] capitalize transition ${tab === item ? "bg-elevated text-ink" : "text-mute hover:text-ink"}`}
                onClick={() => setTab(item)}
              >
                {item}
                {item === "model" && calls.length ? ` ${calls.length}` : ""}
                {item === "tools" && tools.length ? ` ${tools.length}` : ""}
                {item === "failures" && failures.length ? ` ${failures.length}` : ""}
              </button>
            ))}
          </div>
          {tab === "log" && (
            <div className="timeline h-80 space-y-3 overflow-auto pr-1">
              {events.map((event) => (
                <div key={event.id} className="timeline-item">
                  <span className="timeline-dot" />
                  <div className="text-[10px] font-medium uppercase tracking-wider text-faint">{event.kind}</div>
                  <div className="text-[13px] leading-5 text-ink/90">{event.payload.message}</div>
                </div>
              ))}
              {events.length === 0 && <div className="text-sm text-mute">Waiting for the first event.</div>}
            </div>
          )}
          {tab === "model" && (
            <div className="max-h-80 space-y-2 overflow-auto">
              {calls.map((call) => (
                <details key={call.id} className="rounded-lg border border-line bg-sunken px-3 py-2 text-sm">
                  <summary className="cursor-pointer text-[13px]">
                    {call.phase} · {call.provider}/{call.model}
                    <span className="ml-2 font-mono text-[11px] text-faint">{call.tokens_in + call.tokens_out} tok · {call.latency_ms}ms</span>
                  </summary>
                  {call.prompt_preview && (
                    <>
                      <div className="mt-2 text-[10px] font-medium uppercase tracking-wider text-faint">Prompt</div>
                      <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] leading-5 text-mute">{call.prompt_preview}</pre>
                    </>
                  )}
                  <div className="mt-2 text-[10px] font-medium uppercase tracking-wider text-faint">Response</div>
                  <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] leading-5 text-mute">{call.response_preview}</pre>
                </details>
              ))}
              {calls.length === 0 && <p className="text-sm text-mute">No model calls yet.</p>}
            </div>
          )}
          {tab === "tools" && (
            <div className="max-h-80 space-y-2 overflow-auto">
              {tools.map((call) => (
                <div key={call.id} className="rounded-lg border border-line px-3 py-2">
                  <div className="flex items-center justify-between gap-2 text-[13px]">
                    <span className="font-mono">{toolLabel(call.name)}</span>
                    <span className={call.ok ? "text-ok" : "text-bad"}>{call.ok ? "ok" : "failed"} · {call.elapsed_ms}ms</span>
                  </div>
                  {call.args && <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-faint">{pretty(call.args)}</pre>}
                  <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-mute">{call.result_preview}</pre>
                </div>
              ))}
              {tools.length === 0 && <p className="text-sm text-mute">No tool calls yet.</p>}
            </div>
          )}
          {tab === "failures" && (
            <div className="max-h-80 space-y-2 overflow-auto">
              {failures.map((failure, index) => (
                <div key={`${failure.task_key}-${index}`} className="rounded-lg border border-line px-3 py-2 text-[13px]">
                  <div className="flex items-center justify-between">
                    <span className="font-mono">{failure.task_key}</span>
                    <span className={failure.resolved ? "text-ok" : "text-bad"}>{failure.resolved ? "resolved" : "open"}</span>
                  </div>
                  <div className="mt-1 text-mute">
                    {failure.failure_class} · {failure.strategy} · attempt {failure.attempt}
                    {typeof failure.risk === "number" ? ` · risk ${failure.risk.toFixed(2)}` : ""}
                  </div>
                  {failure.evidence && <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] leading-5 text-faint">{failure.evidence}</pre>}
                </div>
              ))}
              {failures.length === 0 && <p className="text-sm text-mute">Nothing failed. Recovery stays idle until a check misses.</p>}
            </div>
          )}
        </div>
        <div className="panel p-4">
          <div className="text-[13px] font-medium">Tokens by task</div>
          <div className="mt-4 space-y-3">
            {(run.tasks || []).map((task) => {
              const row = byTask.get(task.id) || { inn: 0, out: 0 };
              const total = row.inn + row.out;
              const width = Math.round((total / maxTokens) * 100);
              return (
                <div key={task.id}>
                  <div className="mb-1 flex items-center justify-between text-[12px]">
                    <span className="truncate text-mute">{task.task_key}</span>
                    <span className="font-mono text-faint">{total.toLocaleString()}</span>
                  </div>
                  <div className="meter">
                    <span style={{ width: `${width}%` }} />
                  </div>
                </div>
              );
            })}
            {(run.tasks || []).length === 0 && <p className="text-sm text-mute">Tasks appear after planning.</p>}
          </div>
        </div>
      </section>
    </div>
  );
}

function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    read_file: "Read",
    write_file: "Write",
    search: "Search",
    list_dir: "List",
    terminal: "Terminal",
    git: "Git",
    kg_query: "Graph",
    finish: "Finish",
  };
  return labels[name] || name;
}

function pretty(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function transcript(calls: Run["llm_calls"], tools: Run["tool_calls"]) {
  const steps: Array<
    | { kind: "model"; id: string; at: string; phase: string; provider: string; model: string; response: string }
    | { kind: "tool"; id: string; at: string; name: string; ok: number; elapsed: number; args: string; result: string }
  > = [];
  for (const call of calls || []) {
    steps.push({
      kind: "model",
      id: call.id,
      at: call.created_at || "",
      phase: call.phase,
      provider: call.provider,
      model: call.model,
      response: call.response_preview,
    });
  }
  for (const call of tools || []) {
    steps.push({
      kind: "tool",
      id: call.id,
      at: call.created_at || "",
      name: call.name,
      ok: call.ok,
      elapsed: call.elapsed_ms,
      args: pretty(call.args || ""),
      result: call.result_preview,
    });
  }
  return steps.sort((a, b) => a.at.localeCompare(b.at));
}

function Metric({ label, value, hint, meter }: { label: string; value: string; hint: string; meter?: number }) {
  return (
    <div className="panel px-4 py-3">
      <div className="kicker">{label}</div>
      <div className="mt-1 text-[22px] font-semibold tracking-tight">{value}</div>
      <div className="text-[11px] text-faint">{hint}</div>
      {typeof meter === "number" && (
        <div className="meter mt-2">
          <span style={{ width: `${Math.round(meter * 100)}%` }} />
        </div>
      )}
    </div>
  );
}
