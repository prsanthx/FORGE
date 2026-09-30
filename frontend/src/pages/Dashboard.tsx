import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtMs, fmtRate, fmtWhen, isLive, statusTone } from "../format";
import { saveSelectedConfig } from "../theme";
import type { ForgeConfig, Repo, Run, StudioSummary } from "../types";

const SAMPLE =
  "I am not a programmer. Please add a way to mark a todo as done.\nWhen a todo is marked done, its done flag becomes true.\nKeep add, list, get, and remove working.\nAdd a unit test for marking a todo done.";

const STAGES = [
  ["planning", "Plan"],
  ["verification", "Verify"],
  ["recovery", "Recover"],
  ["git_checkpoints", "Checkpoint"],
] as const;

export default function Dashboard({ onOpen }: { onOpen: (id: string) => void }) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [configs, setConfigs] = useState<ForgeConfig[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [repoId, setRepoId] = useState("");
  const [config, setConfig] = useState("full_forge");
  const [goal, setGoal] = useState(SAMPLE);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [inventory, setInventory] = useState<StudioSummary | null>(null);
  const [query, setQuery] = useState("");

  async function refresh() {
    const [repoRows, configRows, runRows] = await Promise.all([api.repos(), api.configs(), api.runs()]);
    setRepos(repoRows);
    setConfigs(configRows);
    setRuns(runRows);
    setRepoId((current) => current || repoRows[0]?.id || "");
    setConfig((current) => current || configRows.find((item) => item.name === "full_forge")?.name || configRows[0]?.name || "full_forge");
    setReady(true);
  }

  useEffect(() => {
    refresh().catch((err: Error) => {
      setError(err.message);
      setReady(true);
    });
    const timer = window.setInterval(() => {
      api.runs().then(setRuns).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!config) return;
    saveSelectedConfig(config);
    api
      .studio(config)
      .then((view) => setInventory(view.summary))
      .catch(() => setInventory(null));
  }, [config]);

  async function launch() {
    setBusy(true);
    setError("");
    try {
      const run = await api.createRun({ repo_id: repoId, config, goal });
      onOpen(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not start run");
    } finally {
      setBusy(false);
    }
  }

  const tokens = runs.reduce((sum, run) => sum + (run.metrics?.tokens || 0), 0);
  const active = runs.filter((run) => isLive(run.status)).length;
  const verified = runs.filter((run) => (run.metrics?.verification_pass_rate || 0) >= 1).length;
  const selected = configs.find((item) => item.name === config);
  const filtered = runs.filter((run) => {
    const hay = `${run.goal} ${run.id} ${run.config_name} ${run.status}`.toLowerCase();
    return hay.includes(query.trim().toLowerCase());
  });

  return (
    <div className="stagger space-y-8">
      <div className="mx-auto flex w-full max-w-3xl flex-col pt-2 md:pt-8">
        <h1 className="page-title text-center">What should FORGE change?</h1>
        <p className="mx-auto mt-2 max-w-xl text-center text-[13px] leading-6 text-mute">
          Describe the change. FORGE plans it, checks the result, and recovers when the model slips.
        </p>

      {!ready ? (
        <div className="mt-6 grid gap-3">
          <div className="skeleton h-40 rounded-2xl" />
        </div>
      ) : (
        <>
          <section className="composer mt-5 p-3 sm:p-4">
            <div className="flex items-center justify-between px-1">
              <span className="text-[12px] font-medium text-mute">New run</span>
              <span className="font-mono text-[11px] text-faint">⌘ Enter</span>
            </div>
            <textarea
              className="mt-2 h-28 w-full resize-none bg-transparent px-1 py-1 font-mono text-[13px] leading-6 text-ink outline-none placeholder:text-faint"
              value={goal}
              placeholder="Describe the change you want in the repository."
              onChange={(event) => setGoal(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  if (!busy && repoId && goal.trim()) launch();
                }
              }}
            />
            <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-3">
              <select className="field max-w-[240px] py-1.5" value={repoId} onChange={(event) => setRepoId(event.target.value)}>
                {repos.length === 0 && <option value="">Connect a repo first</option>}
                {repos.map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.name} · {repo.source}
                  </option>
                ))}
              </select>
              <select className="field max-w-[200px] py-1.5" value={config} onChange={(event) => setConfig(event.target.value)}>
                {configs.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
              <button className="btn-ghost" onClick={() => setGoal(SAMPLE)}>
                Sample goal
              </button>
              <div className="ml-auto flex items-center gap-3">
                {error && <span className="text-[12px] text-bad">{error}</span>}
                <button className="btn-primary px-4" disabled={busy || !repoId || !goal.trim()} onClick={launch}>
                  {busy ? "Starting" : "Run"}
                  <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
                    <path d="M4 3.2v9.6l9-4.8-9-4.8z" />
                  </svg>
                </button>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 px-0.5">
              {STAGES.map(([key, label], index) => {
                const on = Boolean(selected?.features?.[key]);
                return (
                  <div key={key} className="flex items-center gap-2">
                    <span className={`chip ${on ? "chip-on" : "opacity-50"}`}>{label}</span>
                    {index < STAGES.length - 1 && <span className="text-faint">→</span>}
                  </div>
                );
              })}
              <a href="#/studio" className="ml-auto text-[11px] text-faint transition hover:text-ink">
                {inventory
                  ? `${inventory.tools_in_prompt} tools · ${inventory.skills_enabled} skills`
                  : "Tools and skills"}
              </a>
              <span className="hidden text-[11px] text-faint sm:inline">
                {selected?.llm?.provider || "mock"} / {selected?.llm?.model || "mock-small"}
              </span>
            </div>
          </section>
        </>
      )}
      </div>

      {ready && (
        <>
          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ["Runs", String(runs.length), "All sessions"],
              ["Active", String(active), "In flight"],
              ["Verified", String(verified), "Checks at 100%"],
              ["Tokens", tokens.toLocaleString(), "Model usage"],
            ].map(([label, value, hint]) => (
              <div key={label} className="panel px-4 py-3">
                <div className="kicker">{label}</div>
                <div className="mt-1 text-[22px] font-medium tracking-tight">{value}</div>
                <div className="text-[11px] text-faint">{hint}</div>
              </div>
            ))}
          </section>

          <section className="panel overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
              <div className="text-[13px] font-medium">Recent runs</div>
              <label className="sr-only" htmlFor="run-search">
                Filter runs
              </label>
              <input
                id="run-search"
                className="field max-w-xs py-1.5 text-[12px]"
                placeholder="Filter by goal, id, or status"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            {runs.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <div className="text-sm font-medium">No runs yet</div>
                <p className="mx-auto mt-1 max-w-md text-[13px] leading-6 text-mute">
                  Connect <span className="font-mono text-ink">examples/todo_api</span>, keep full_forge selected, and run the sample goal.
                </p>
              </div>
            ) : filtered.length === 0 ? (
              <div className="px-4 py-8 text-center text-[13px] text-mute">No runs match that filter.</div>
            ) : (
              <div>
                <div className="hidden grid-cols-[1fr_120px_88px_88px_72px] gap-3 px-4 py-2 text-[10px] font-medium uppercase tracking-wider text-faint md:grid">
                  <span>Goal</span>
                  <span>Status</span>
                  <span>Verify</span>
                  <span>Tokens</span>
                  <span>Time</span>
                </div>
                <ul>
                  {filtered.map((run) => (
                    <li key={run.id} className="border-t border-line">
                      <button
                        className="grid w-full grid-cols-1 items-center gap-3 px-4 py-3 text-left transition hover:bg-elevated md:grid-cols-[1fr_120px_88px_88px_72px]"
                        onClick={() => onOpen(run.id)}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-[13px] text-ink">{run.goal.replace(/\s+/g, " ").slice(0, 96)}</span>
                          <span className="mt-0.5 block font-mono text-[11px] text-faint">
                            {run.id} · {run.config_name}
                            {run.started_at ? ` · ${fmtWhen(run.started_at)}` : ""}
                          </span>
                        </span>
                        <span className={`inline-flex w-fit items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${statusTone(run.status)}`}>
                          <span className={`status-dot ${isLive(run.status) ? "is-live" : ""}`} />
                          {run.status.replaceAll("_", " ")}
                        </span>
                        <span className="text-[12px] text-mute">
                          <span className="text-faint md:sr-only">Verify </span>
                          {fmtRate(run.metrics?.verification_pass_rate)}
                        </span>
                        <span className="font-mono text-[12px] text-mute">
                          <span className="text-faint md:sr-only">Tokens </span>
                          {(run.metrics?.tokens ?? 0).toLocaleString()}
                        </span>
                        <span className="font-mono text-[12px] text-faint">
                          <span className="md:sr-only">Time </span>
                          {fmtMs(run.metrics?.elapsed_ms)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
