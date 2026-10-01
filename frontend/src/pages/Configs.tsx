import { useEffect, useState } from "react";
import { api } from "../api";
import type { ForgeConfig } from "../types";

const CONTEXT = [
  ["spill", "Spill large output"],
  ["dedupe_reads", "De-duplicate reads"],
  ["mask_old", "Mask old output"],
  ["agents_md", "AGENTS.md"],
  ["prompt_cache", "Prompt cache"],
] as const;

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
    setMessage(`Saved ${saved.name}`);
  }

  async function toggleContext(config: ForgeConfig, key: (typeof CONTEXT)[number][0]) {
    const context = { ...(config.context || {}), [key]: !config.context?.[key] };
    const saved = await api.saveConfig(config.name, { ...config, context });
    setConfigs((current) => current.map((item) => (item.name === saved.name ? saved : item)));
    setMessage(`Saved ${saved.name}`);
  }

  async function updateNumber(config: ForgeConfig, field: "max_retries" | "risk_threshold", value: number) {
    if (!Number.isFinite(value)) return;
    const current = config.recovery?.[field];
    if (current === value) return;
    const next: ForgeConfig = {
      ...config,
      recovery: { ...(config.recovery || {}), [field]: value },
    };
    const saved = await api.saveConfig(config.name, next);
    setConfigs((rows) => rows.map((item) => (item.name === saved.name ? saved : item)));
    setMessage(`Saved ${saved.name}`);
  }

  return (
    <div className="stagger space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="kicker">Control surface</div>
          <h1 className="page-title">Configs</h1>
          <p className="mt-2 max-w-2xl text-[13px] leading-6 text-mute">
            Baseline through full FORGE. Toggles write back to the YAML files the harness reads.
          </p>
        </div>
        {message && <p className="text-[12px] text-accent">{message}</p>}
      </header>
      <div className="grid gap-4 lg:grid-cols-2">
        {configs.map((config) => {
          const enabled = FLAGS.filter(([key]) => config.features?.[key]).length;
          return (
            <article key={config.name} className="panel panel-hover p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-mono text-[15px] font-medium">{config.name}</div>
                  <p className="mt-2 text-[13px] leading-6 text-mute">{config.description}</p>
                </div>
                <span className="chip chip-on">{enabled}/{FLAGS.length}</span>
              </div>
              <div className="mt-3 font-mono text-[11px] text-faint">
                {config.llm?.provider}/{config.llm?.model} · {config.executor?.max_steps_per_task} steps · {(config.verification?.levels || []).join(" · ") || "no funnel"}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {FLAGS.map(([key, label]) => {
                  const on = Boolean(config.features?.[key]);
                  return (
                    <button key={key} className={`chip ${on ? "chip-on" : ""}`} onClick={() => toggle(config, key)}>
                      <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${on ? "bg-accent" : "bg-line"}`} />
                      {label}
                    </button>
                  );
                })}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {CONTEXT.map(([key, label]) => {
                  const on = config.context?.[key] !== false;
                  return (
                    <button key={key} className={`chip ${on ? "chip-on" : ""}`} onClick={() => toggleContext(config, key)}>
                      {label}
                    </button>
                  );
                })}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <NumberField
                  label="Max retries"
                  value={config.recovery?.max_retries ?? 0}
                  min={0}
                  onCommit={(value) => updateNumber(config, "max_retries", value)}
                />
                <NumberField
                  label="Ask-human risk"
                  value={config.recovery?.risk_threshold ?? 1}
                  min={0}
                  max={1}
                  step={0.01}
                  onCommit={(value) => updateNumber(config, "risk_threshold", value)}
                />
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onCommit,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onCommit: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <label>
      <span className="kicker">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        className="field mt-1"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => onCommit(Number(text))}
        onKeyDown={(event) => {
          if (event.key === "Enter") (event.target as HTMLInputElement).blur();
        }}
      />
    </label>
  );
}
