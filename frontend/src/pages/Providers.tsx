import { useEffect, useState } from "react";
import { api } from "../api";
import type { ProviderInfo } from "../types";

export default function Providers() {
  const [rows, setRows] = useState<ProviderInfo[]>([]);
  const [drafts, setDrafts] = useState<Record<string, { model: string; base_url: string; api_key: string }>>({});
  const [health, setHealth] = useState<Record<string, { ok: boolean; detail: string }>>({});

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
    const result = await api.providerHealth({
      provider,
      model: draft?.model || "",
      base_url: draft?.base_url || "",
      api_key: draft?.api_key || "",
    });
    setHealth((current) => ({ ...current, [provider]: result }));
  }

  return (
    <div className="space-y-5">
      <header>
        <div className="kicker">Models</div>
        <h1 className="font-display text-4xl">Providers</h1>
        <p className="mt-2 max-w-2xl text-sm text-mute">
          MockLLM runs the demo offline. Ollama, LM Studio, Hugging Face, NVIDIA NIM, Google, and any OpenAI-compatible
          endpoint use the same tool loop when you point a config at them.
        </p>
      </header>
      <div className="grid grid-cols-2 gap-4">
        {rows.map((row) => {
          const draft = drafts[row.provider] || { model: "", base_url: "", api_key: "" };
          const state = health[row.provider];
          return (
            <article key={row.provider} className="panel p-4">
              <div className="flex items-center justify-between">
                <h2 className="font-display text-2xl">{row.provider}</h2>
                <span className={`text-xs ${state ? (state.ok ? "text-ok" : "text-bad") : "text-mute"}`}>
                  {state ? (state.ok ? "healthy" : "unreachable") : "unchecked"}
                </span>
              </div>
              <label className="mt-3 block text-xs text-mute">
                Model
                <input className="mt-1 w-full rounded border border-line bg-black/30 px-2 py-1 text-sm text-ink" value={draft.model} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, model: event.target.value } })} />
              </label>
              <label className="mt-2 block text-xs text-mute">
                Base URL
                <input className="mt-1 w-full rounded border border-line bg-black/30 px-2 py-1 font-mono text-xs text-ink" value={draft.base_url} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, base_url: event.target.value } })} />
              </label>
              <label className="mt-2 block text-xs text-mute">
                API key {row.api_key_env ? `(or ${row.api_key_env})` : ""}
                <input type="password" className="mt-1 w-full rounded border border-line bg-black/30 px-2 py-1 text-sm text-ink" value={draft.api_key} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, api_key: event.target.value } })} />
              </label>
              <button className="mt-3 rounded border border-brass px-3 py-1 text-sm text-brass" onClick={() => check(row.provider)}>
                Check health
              </button>
              {state && <p className="mt-2 text-xs text-mute">{state.detail}</p>}
            </article>
          );
        })}
      </div>
    </div>
  );
}
