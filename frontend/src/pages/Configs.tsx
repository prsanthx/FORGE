import { useEffect, useState } from "react";
import { api } from "../api";
import type { ForgeConfig } from "../types";

const FLAGS = [
  ["planning", "Planning"],
  ["hierarchical_planning", "Hierarchical planning"],
  ["verification", "Verification funnel"],
  ["recovery", "Adaptive recovery"],
  ["kg_retrieval", "Knowledge graph"],
  ["context_packs", "Context packs"],
  ["graph_rag", "Graph RAG"],
  ["git_checkpoints", "Git checkpoints"],
  ["failure_memory", "Failure memory"],
];

export default function Configs() {
  const [configs, setConfigs] = useState<ForgeConfig[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.configs().then(setConfigs).catch((err: Error) => setMessage(err.message));
  }, []);

  async function toggle(config: ForgeConfig, key: string) {
    const next: ForgeConfig = {
      ...config,
      features: { ...config.features, [key]: !config.features?.[key] },
    };
    const saved = await api.saveConfig(config.name, next);
    setConfigs((current) => current.map((item) => (item.name === saved.name ? saved : item)));
    setMessage(`saved ${saved.name}`);
  }

  async function updateNumber(config: ForgeConfig, field: "max_retries" | "risk_threshold", value: number) {
    const next: ForgeConfig = {
      ...config,
      recovery: { ...(config.recovery || {}), [field]: value },
    };
    const saved = await api.saveConfig(config.name, next);
    setConfigs((current) => current.map((item) => (item.name === saved.name ? saved : item)));
  }

  return (
    <div className="space-y-5">
      <header>
        <div className="kicker">Control</div>
        <h1 className="font-display text-4xl">Ablation configs</h1>
        <p className="mt-2 max-w-2xl text-sm text-mute">
          Baseline, planning, planning plus verification, and full FORGE. Toggles write back to the YAML files.
        </p>
        {message && <p className="mt-2 text-xs text-brass">{message}</p>}
      </header>
      <div className="grid grid-cols-2 gap-4">
        {configs.map((config) => (
          <article key={config.name} className="panel p-4">
            <div className="font-display text-2xl">{config.name}</div>
            <p className="mt-2 text-sm leading-6 text-mute">{config.description}</p>
            <div className="mt-3 text-xs text-mute">
              model {config.llm?.provider}/{config.llm?.model} · steps {config.executor?.max_steps_per_task} · levels{" "}
              {(config.verification?.levels || []).join(", ") || "none"}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {FLAGS.map(([key, label]) => {
                const on = Boolean(config.features?.[key]);
                return (
                  <button
                    key={key}
                    className={`rounded-full border px-3 py-1 text-xs ${on ? "border-brass text-brass" : "border-line text-mute"}`}
                    onClick={() => toggle(config, key)}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <label>
                <span className="text-mute">Max retries</span>
                <input
                  type="number"
                  min={0}
                  className="mt-1 w-full rounded border border-line bg-black/30 px-2 py-1"
                  value={config.recovery?.max_retries ?? 0}
                  onChange={(event) => updateNumber(config, "max_retries", Number(event.target.value))}
                />
              </label>
              <label>
                <span className="text-mute">Ask-human risk</span>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  className="mt-1 w-full rounded border border-line bg-black/30 px-2 py-1"
                  value={config.recovery?.risk_threshold ?? 1}
                  onChange={(event) => updateNumber(config, "risk_threshold", Number(event.target.value))}
                />
              </label>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
