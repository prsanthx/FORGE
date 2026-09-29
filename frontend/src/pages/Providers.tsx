import { useEffect, useState } from "react";
import { api } from "../api";
import type { ProviderInfo } from "../types";

export default function Providers() {
  const [rows, setRows] = useState<ProviderInfo[]>([]);
  const [drafts, setDrafts] = useState<Record<string, { model: string; base_url: string; api_key: string }>>({});
  const [health, setHealth] = useState<Record<string, { ok: boolean; detail: string }>>({});
  const [checking, setChecking] = useState("");

  useEffect(() => {
    api.providers().then((list) => {
      setRows(list);
      const next: Record<string, { model: string; base_url: string; api_key: string }> = {};
      for (const row of list) next[row.provider] = { model: row.model, base_url: row.base_url, api_key: "" };
      setDrafts(next);
    });
  }, []);

  async function check(provider: string) {
    const draft = drafts[provider];
    setChecking(provider);
    try {
      const result = await api.providerHealth({
        provider,
        model: draft?.model || "",
        base_url: draft?.base_url || "",
        api_key: draft?.api_key || "",
      });
      setHealth((current) => ({ ...current, [provider]: result }));
    } finally {
      setChecking("");
    }
  }

  return (
    <div className="stagger space-y-5">
      <header>
        <div className="kicker">Models</div>
        <h1 className="mt-1 text-[26px] font-semibold tracking-tight">Providers</h1>
        <p className="mt-2 max-w-2xl text-[13px] leading-6 text-mute">
          MockLLM runs the demo offline. Point a config at Ollama, LM Studio, Hugging Face, NVIDIA NIM, Google, or any OpenAI-compatible endpoint and the tool loop stays the same.
        </p>
      </header>
      <div className="grid gap-4 lg:grid-cols-2">
        {rows.map((row) => {
          const draft = drafts[row.provider] || { model: "", base_url: "", api_key: "" };
          const state = health[row.provider];
          return (
            <article key={row.provider} className="panel panel-hover p-4">
              <div className="flex items-center justify-between">
                <h2 className="font-mono text-[15px] font-medium">{row.provider}</h2>
                <span className={`inline-flex items-center gap-1.5 text-[11px] ${state ? (state.ok ? "text-ok" : "text-bad") : "text-faint"}`}>
                  <span className={`status-dot ${checking === row.provider ? "is-live text-accent" : ""}`} />
                  {checking === row.provider ? "checking" : state ? (state.ok ? "healthy" : "unreachable") : "unchecked"}
                </span>
              </div>
              <label className="mt-3 block">
                <span className="kicker">Model</span>
                <input className="field mt-1" value={draft.model} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, model: event.target.value } })} />
              </label>
              <label className="mt-2 block">
                <span className="kicker">Base URL</span>
                <input className="field mt-1 font-mono text-[12px]" value={draft.base_url} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, base_url: event.target.value } })} />
              </label>
              <label className="mt-2 block">
                <span className="kicker">API key {row.api_key_env ? `or ${row.api_key_env}` : ""}</span>
                <input type="password" className="field mt-1" value={draft.api_key} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, api_key: event.target.value } })} />
              </label>
              <button className="btn-ghost mt-3" onClick={() => check(row.provider)} disabled={checking === row.provider}>
                Check health
              </button>
              {state && <p className="mt-2 text-[12px] leading-5 text-mute">{state.detail}</p>}
            </article>
          );
        })}
      </div>
    </div>
  );
}
