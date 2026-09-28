import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtMs, fmtRate, statusTone } from "../format";
import type { ForgeConfig, Repo, Run } from "../types";

const SAMPLE =
  "I am not a programmer. Please add a way to mark a todo as done.\nWhen a todo is marked done, its done flag becomes true.\nKeep add, list, get, and remove working.\nAdd a unit test for marking a todo done.";

export default function Dashboard({ onOpen }: { onOpen: (id: string) => void }) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [configs, setConfigs] = useState<ForgeConfig[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [repoId, setRepoId] = useState("");
  const [config, setConfig] = useState("full_forge");
  const [goal, setGoal] = useState(SAMPLE);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [repoRows, configRows, runRows] = await Promise.all([api.repos(), api.configs(), api.runs()]);
    setRepos(repoRows);
    setConfigs(configRows);
    setRuns(runRows);
    setRepoId((current) => current || repoRows[0]?.id || "");
    setConfig((current) => current || configRows.find((item) => item.name === "full_forge")?.name || configRows[0]?.name || "full_forge");
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
    const timer = window.setInterval(() => {
      api.runs().then(setRuns).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, []);

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
  const active = runs.filter((run) => ["queued", "planning", "running", "awaiting_human"].includes(run.status)).length;

  return (
    <div className="space-y-6">
      <header>
        <div className="kicker">Dashboard</div>
        <h1 className="mt-1 font-display text-4xl">Ongoing work</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-mute">
          Connect a repo, pick an ablation, and describe the change in plain language. FORGE plans the work,
          checks it, and recovers when a small model slips.
        </p>
      </header>
      <section className="grid grid-cols-3 gap-3">
        {[
          ["Runs", String(runs.length)],
          ["Active", String(active)],
          ["Tokens", tokens.toLocaleString()],
        ].map(([label, value]) => (
          <div key={label} className="panel px-4 py-3">
            <div className="kicker">{label}</div>
            <div className="mt-1 font-display text-3xl">{value}</div>
          </div>
        ))}
      </section>
      <section className="panel p-4">
        <div className="kicker">New run</div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="text-sm">
            <span className="text-mute">Repository</span>
            <select className="mt-1 w-full rounded border border-line bg-black/30 px-2 py-2" value={repoId} onChange={(event) => setRepoId(event.target.value)}>
              {repos.length === 0 && <option value="">Connect a repo first</option>}
              {repos.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name} · {repo.source}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-mute">Config</span>
            <select className="mt-1 w-full rounded border border-line bg-black/30 px-2 py-2" value={config} onChange={(event) => setConfig(event.target.value)}>
              {configs.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <textarea
          className="mt-3 h-32 w-full rounded border border-line bg-black/30 p-3 font-mono text-sm"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
        />
        <div className="mt-3 flex items-center gap-3">
          <button
            className="rounded bg-brass px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
            disabled={busy || !repoId || !goal.trim()}
            onClick={launch}
          >
            {busy ? "Starting…" : "Run FORGE"}
          </button>
          <button className="text-sm text-mute underline" onClick={() => setGoal(SAMPLE)}>
            Use the sample goal
          </button>
          {error && <span className="text-sm text-bad">{error}</span>}
        </div>
      </section>
      <section className="panel overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-mute">
            <tr>
              <th className="px-4 py-3">Run</th>
              <th>Config</th>
              <th>Status</th>
              <th>Verify</th>
              <th>Recover</th>
              <th>Tokens</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-t border-line hover:bg-white/5">
                <td className="px-4 py-3">
                  <button className="text-left text-brass" onClick={() => onOpen(run.id)}>
                    {run.goal.slice(0, 72)}
                  </button>
                  <div className="text-[11px] text-mute">{run.id}</div>
                </td>
                <td>{run.config_name}</td>
                <td>
                  <span className={`rounded border px-2 py-0.5 text-xs ${statusTone(run.status)}`}>{run.status}</span>
                </td>
                <td>{fmtRate(run.metrics?.verification_pass_rate)}</td>
                <td>{fmtRate(run.metrics?.recovery_success)}</td>
                <td>{run.metrics?.tokens ?? 0}</td>
                <td>{fmtMs(run.metrics?.elapsed_ms)}</td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td className="px-4 py-6 text-mute" colSpan={7}>
                  No runs yet. Connect <span className="text-ink">examples/todo_api</span> and start one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
