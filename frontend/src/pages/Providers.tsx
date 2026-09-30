import { useEffect, useState } from "react";
import { api } from "../api";
import { readTheme, saveTheme, type ThemeChoice } from "../theme";
import type { ForgeConfig, ProviderInfo } from "../types";

type SettingsTab = "providers" | "appearance";

export default function Providers() {
  const initial = new URLSearchParams(window.location.hash.split("?")[1] || "").get("tab");
  const [tab, setTab] = useState<SettingsTab>(initial === "appearance" ? "appearance" : "providers");
  const [rows, setRows] = useState<ProviderInfo[]>([]);
  const [configs, setConfigs] = useState<ForgeConfig[]>([]);
  const [target, setTarget] = useState("full_forge");
  const [drafts, setDrafts] = useState<Record<string, { model: string; base_url: string; api_key: string }>>({});
  const [health, setHealth] = useState<Record<string, { ok: boolean; detail: string }>>({});
  const [checking, setChecking] = useState("");
  const [note, setNote] = useState("");
  const [theme, setTheme] = useState<ThemeChoice>(readTheme());

  useEffect(() => {
    Promise.all([api.providers(), api.configs()]).then(([list, configRows]) => {
      setRows(list);
      setConfigs(configRows);
      setTarget(configRows.find((item) => item.name === "full_forge")?.name || configRows[0]?.name || "full_forge");
      const next: Record<string, { model: string; base_url: string; api_key: string }> = {};
      for (const row of list) next[row.provider] = { model: row.model, base_url: row.base_url, api_key: "" };
      setDrafts(next);
    });
  }, []);

  async function check(provider: string) {
    const draft = drafts[provider];
    setChecking(provider);
    setNote("");
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

  async function saveInto(provider: string) {
    const config = configs.find((item) => item.name === target);
    const draft = drafts[provider];
    if (!config || !draft) return;
    const saved = await api.saveConfig(config.name, {
      ...config,
      llm: {
        ...(config.llm || {}),
        provider,
        model: draft.model,
        base_url: draft.base_url || null,
      },
    });
    setConfigs((current) => current.map((item) => (item.name === saved.name ? saved : item)));
    setNote(`Saved ${provider} into ${saved.name}. The API key stays in this form and is not written to the config.`);
  }

  function chooseTheme(choice: ThemeChoice) {
    setTheme(choice);
    saveTheme(choice);
  }

  return (
    <div className="stagger space-y-5">
      <header>
        <div className="kicker">Preferences</div>
        <h1 className="mt-1 text-[26px] font-semibold tracking-tight">Settings</h1>
        <p className="mt-2 max-w-2xl text-[13px] leading-6 text-mute">
          Appearance stays on this machine. Provider health checks are ephemeral until you save a provider into a config.
        </p>
      </header>
      <div className="seg" role="tablist" aria-label="Settings">
        <button role="tab" aria-selected={tab === "providers"} className={tab === "providers" ? "is-on" : ""} onClick={() => setTab("providers")}>
          Providers
        </button>
        <button role="tab" aria-selected={tab === "appearance"} className={tab === "appearance" ? "is-on" : ""} onClick={() => setTab("appearance")}>
          Appearance
        </button>
      </div>

      {tab === "appearance" && (
        <section className="panel max-w-xl p-4">
          <div className="text-[14px] font-medium">Color mode</div>
          <p className="mt-1 text-[13px] leading-6 text-mute">Light, dark, or match the system setting.</p>
          <div className="seg mt-3" role="radiogroup" aria-label="Color mode">
            {(
              [
                ["light", "Light"],
                ["system", "Match system"],
                ["dark", "Dark"],
              ] as const
            ).map(([value, label]) => (
              <button key={value} role="radio" aria-checked={theme === value} className={theme === value ? "is-on" : ""} onClick={() => chooseTheme(value)}>
                {label}
              </button>
            ))}
          </div>
        </section>
      )}

      {tab === "providers" && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-mute">
            <label htmlFor="config-target">Save into</label>
            <select id="config-target" className="field max-w-[220px] py-1.5" value={target} onChange={(event) => setTarget(event.target.value)}>
              {configs.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
            {note && <span className="text-accent">{note}</span>}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {rows.map((row) => {
              const draft = drafts[row.provider] || { model: "", base_url: "", api_key: "" };
              const state = health[row.provider];
              return (
                <article key={row.provider} className="panel p-4">
                  <div className="flex items-center justify-between">
                    <h2 className="font-mono text-[15px] font-medium">{row.provider}</h2>
                    <span className={`inline-flex items-center gap-1.5 text-[11px] ${state ? (state.ok ? "text-ok" : "text-bad") : "text-faint"}`}>
                      <span className={`status-dot ${checking === row.provider ? "is-live text-accent" : ""}`} />
                      {checking === row.provider ? "checking" : state ? (state.ok ? "healthy" : "unreachable") : "unchecked"}
                    </span>
                  </div>
                  <label className="mt-3 block">
                    <span className="kicker">Model</span>
                    <input className="field mt-1" aria-label={`${row.provider} model`} value={draft.model} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, model: event.target.value } })} />
                  </label>
                  <label className="mt-2 block">
                    <span className="kicker">Base URL</span>
                    <input className="field mt-1 font-mono text-[12px]" aria-label={`${row.provider} base URL`} value={draft.base_url} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, base_url: event.target.value } })} />
                  </label>
                  <label className="mt-2 block">
                    <span className="kicker">API key {row.api_key_env ? `or ${row.api_key_env}` : ""}</span>
                    <input type="password" className="field mt-1" aria-label={`${row.provider} API key`} value={draft.api_key} onChange={(event) => setDrafts({ ...drafts, [row.provider]: { ...draft, api_key: event.target.value } })} />
                  </label>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button className="btn-ghost" onClick={() => check(row.provider)} disabled={checking === row.provider}>
                      Check health
                    </button>
                    <button className="btn" onClick={() => saveInto(row.provider)}>
                      Save into config
                    </button>
                  </div>
                  <p className="mt-2 text-[11px] leading-5 text-faint">Health check does not change the next run until you save.</p>
                  {state && <p className="mt-1 text-[12px] leading-5 text-mute">{state.detail}</p>}
                </article>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
