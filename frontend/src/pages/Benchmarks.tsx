import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtRate } from "../format";
import type { BenchTask, Benchmark, Repo } from "../types";

const METRICS = [
  ["task_completion", "Completion"],
  ["recovery_success", "Recovery"],
  ["verification_pass_rate", "Verification"],
  ["regression_rate", "Regression"],
  ["human_intervention_rate", "Human"],
];

const CONFIGS = ["baseline", "planning", "planning_verify", "full_forge"];

export default function Benchmarks() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [tasks, setTasks] = useState<BenchTask[]>([]);
  const [repoId, setRepoId] = useState("");
  const [pickedTasks, setPickedTasks] = useState<string[]>([]);
  const [configs, setConfigs] = useState(CONFIGS);
  const [record, setRecord] = useState<Benchmark | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.repos(), api.benchTasks(), api.benchmarks()]).then(([repoRows, taskRows, history]) => {
      setRepos(repoRows);
      setTasks(taskRows);
      setRepoId(repoRows[0]?.id || "");
      setPickedTasks(taskRows.map((task) => task.id));
      if (history[0]) api.benchmark(history[0].id).then(setRecord).catch(() => undefined);
    }).catch((err: Error) => setError(err.message));
  }, []);

  function toggleConfig(name: string) {
    setConfigs((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  }
  function toggleTask(id: string) {
    setPickedTasks((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  async function run() {
    setBusy(true);
    setError("");
    try {
      const result = await api.runBenchmark({ repo_id: repoId, configs, task_ids: pickedTasks });
      setRecord(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "benchmark failed");
    } finally {
      setBusy(false);
    }
  }

  const cells = record?.cells || [];
  const columns = unique(cells.map((cell) => `${cell.difficulty}|${cell.config_name}`));

  return (
    <div className="stagger space-y-5">
      <header>
        <div className="kicker">Ablation matrix</div>
        <h1 className="mt-1 text-[26px] font-semibold tracking-tight">Benchmarks</h1>
        <p className="mt-2 max-w-3xl text-[13px] leading-6 text-mute">
          Each cell is a real harness run scored by an oracle the agent never sees. A dash means that metric did not apply.
        </p>
      </header>
      <section className="panel p-4 text-sm">
        <label className="flex flex-wrap items-center gap-2 text-[13px] text-mute">
          Repository
          <select className="field max-w-xs" value={repoId} onChange={(event) => setRepoId(event.target.value)}>
            {repos.map((repo) => (
              <option key={repo.id} value={repo.id}>{repo.name}</option>
            ))}
          </select>
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          {CONFIGS.map((name) => (
            <button key={name} className={`chip font-mono ${configs.includes(name) ? "chip-on" : ""}`} onClick={() => toggleConfig(name)}>
              {name}
            </button>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {tasks.map((task) => (
            <button key={task.id} className={`chip ${pickedTasks.includes(task.id) ? "border-info/40 bg-info/10 text-info" : ""}`} onClick={() => toggleTask(task.id)}>
              {task.difficulty}: {task.title}
            </button>
          ))}
        </div>
        <button className="btn-primary mt-4" disabled={busy || !repoId} onClick={run}>
          {busy ? "Running harness" : "Run matrix"}
        </button>
        {error && <p className="mt-2 text-bad">{error}</p>}
      </section>
      {!record && (
        <section className="panel px-4 py-10 text-center">
          <div className="text-sm font-medium">No matrix yet</div>
          <p className="mx-auto mt-1 max-w-md text-[13px] leading-6 text-mute">
            Choose configs and tasks, then run the matrix. Scores come from hidden oracles, not a fixture table.
          </p>
        </section>
      )}
      {record && (
        <section className="panel overflow-auto p-4">
          <div className="mb-3 flex items-center justify-between text-[11px] text-faint">
            <span className="font-mono">{record.id}</span>
            <span className="chip">{record.status}</span>
          </div>
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr>
                <th className="p-2 font-medium text-faint">Metric</th>
                {columns.map((column) => (
                  <th key={column} className="p-2 font-normal text-faint">{column.replace("|", " · ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map(([key, label]) => (
                <tr key={key} className="border-t border-white/8">
                  <td className="p-2 text-[13px]">{label}</td>
                  {columns.map((column) => {
                    const [difficulty, config] = column.split("|");
                    const cell = cells.find((item) => item.difficulty === difficulty && item.config_name === config);
                    const value = cell ? (cell.metrics[key] as number | null) : null;
                    return (
                      <td key={column} className={`p-2 font-mono ${heat(key, value)}`}>
                        {fmtRate(value)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function heat(metric: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-faint";
  const good = metric === "regression_rate" || metric === "human_intervention_rate" ? 1 - value : value;
  if (good >= 0.8) return "bg-ok/15 text-ok";
  if (good >= 0.4) return "bg-accent/10 text-accent";
  return "bg-bad/15 text-bad";
}
