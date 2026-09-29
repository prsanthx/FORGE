import { useEffect, useState } from "react";
import { api } from "../api";
import type { ForgeConfig, McpServer, StudioSnapshot } from "../types";

const EMPTY_SKILL = { name: "", description: "", body: "" };
const EMPTY_SERVER = { name: "", transport: "stdio", command: "", args: "", url: "" };

export default function Studio() {
  const [configs, setConfigs] = useState<ForgeConfig[]>([]);
  const [configName, setConfigName] = useState("full_forge");
  const [view, setView] = useState<StudioSnapshot | null>(null);
  const [skill, setSkill] = useState(EMPTY_SKILL);
  const [server, setServer] = useState(EMPTY_SERVER);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  async function reload(name = configName) {
    const [shot, rows] = await Promise.all([api.studio(name), api.configs()]);
    setView(shot);
    setConfigs(rows);
    setConfigName(shot.config || name);
  }

  useEffect(() => {
    reload("full_forge").catch((err: Error) => setError(err.message));
    // The first paint always loads the full harness config.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    try {
      await action();
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed");
    } finally {
      setBusy("");
    }
  }

  async function toggleBuiltin(name: string) {
    const config = configs.find((item) => item.name === configName);
    if (!config) return;
    const current = config.tools?.enabled || [];
    const enabled = current.includes(name) ? current.filter((item) => item !== name) : [...current, name];
    await run(name, () => api.saveConfig(config.name, { ...config, tools: { ...(config.tools || {}), enabled } }));
  }

  const summary = view?.summary;
  const total = summary?.tools_in_prompt || 0;
  const share = (count: number) => (total ? `${(count / total) * 100}%` : "0%");

  return (
    <div className="stagger space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="kicker">Harness</div>
          <h1 className="mt-1 text-[26px] font-semibold tracking-tight">Tools, skills, and servers</h1>
          <p className="mt-2 max-w-2xl text-[13px] leading-6 text-mute">
            This is the inventory the execute loop hands the model, next to planning, verification, and recovery.
          </p>
        </div>
        <label className="text-[11px] text-faint">
          Config
          <select
            className="field mt-1 min-w-[180px]"
            value={configName}
            onChange={(event) => {
              const next = event.target.value;
              setConfigName(next);
              reload(next).catch((err: Error) => setError(err.message));
            }}
          >
            {configs.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      {!view || !summary ? (
        <div className="skeleton h-48 rounded-2xl" />
      ) : (
        <>
          <section className="panel p-5">
            <div className="flex flex-wrap items-end justify-between gap-6">
              <div>
                <div className="kicker">Given to the model</div>
                <div className="mt-1 flex items-baseline gap-3">
                  <span className="text-[52px] font-semibold leading-none tracking-tight">{summary.tools_in_prompt}</span>
                  <span className="text-sm text-mute">tools in the prompt</span>
                </div>
                <p className="mt-3 max-w-xl text-[13px] leading-6 text-mute">
                  {summary.builtin_enabled} workspace tools, finish, and {summary.mcp_tools} tools from connected servers.
                  {" "}
                  {summary.skills_enabled} skills ride along as instructions.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
                {[
                  ["Workspace", summary.builtin_enabled],
                  ["Finish", summary.finish],
                  ["MCP", summary.mcp_tools],
                  ["Skills", summary.skills_enabled],
                ].map(([label, value]) => (
                  <div key={String(label)} className="rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
                    <div className="font-mono text-[20px] font-medium">{value}</div>
                    <div className="mt-1 text-[11px] text-faint">{label}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="mt-4 flex h-1.5 overflow-hidden rounded-full bg-white/5">
              <div className="bg-accent transition-all" style={{ width: share(summary.builtin_enabled) }} />
              <div className="bg-white/80 transition-all" style={{ width: share(summary.finish) }} />
              <div className="bg-info transition-all" style={{ width: share(summary.mcp_tools) }} />
            </div>
            <pre className="mt-4 max-h-72 overflow-auto rounded-xl bg-black/40 p-3 font-mono text-[12px] leading-6 text-ink">
              {["TOOLS:", ...view.prompt_tools.map((name) => `- ${name}`)].join("\n")}
            </pre>
            {error && <p className="mt-3 text-[12px] text-bad">{error}</p>}
          </section>

          <section className="grid items-start gap-4 lg:grid-cols-3">
            <article className="panel p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-[14px] font-medium">Tools</h2>
                <span className="text-[11px] text-faint">{configName}</span>
              </div>
              <p className="mt-1 text-[12px] leading-5 text-mute">Toggles write the selected config. Finish stays on.</p>
              <ul className="mt-3 space-y-2">
                {view.builtin.map((tool) => (
                  <li key={tool.name} className="rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-mono text-[12px]">{tool.name}</div>
                        <div className="text-[11px] text-faint">{tool.group}</div>
                      </div>
                      <button
                        className={`chip ${tool.enabled ? "chip-on" : ""}`}
                        disabled={tool.always || busy === tool.name}
                        onClick={() => toggleBuiltin(tool.name)}
                      >
                        {tool.always ? "Always" : tool.enabled ? "On" : "Off"}
                      </button>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-5 text-mute">{tool.summary}</p>
                  </li>
                ))}
              </ul>
            </article>

            <article className="panel p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-[14px] font-medium">Skills</h2>
                <span className="text-[11px] text-faint">{summary.skills_enabled} enabled</span>
              </div>
              <p className="mt-1 text-[12px] leading-5 text-mute">Enabled skills are appended to the execute prompt.</p>
              <ul className="mt-3 space-y-2">
                {view.skills.map((item) => (
                  <li key={item.id} className="rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-mono text-[12px]">{item.name}</div>
                        <div className="text-[12px] text-mute">{item.description}</div>
                      </div>
                      <button
                        className={`chip ${item.enabled ? "chip-on" : ""}`}
                        onClick={() => run(item.id, () => api.updateSkill(item.id, { enabled: !item.enabled }))}
                      >
                        {item.enabled ? "On" : "Off"}
                      </button>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-5 text-faint">{item.body}</p>
                    <button className="btn-ghost mt-2 px-2 py-1 text-[11px]" onClick={() => run(item.id, () => api.deleteSkill(item.id))}>
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
              <form
                className="mt-3 space-y-2 border-t border-white/8 pt-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  run("skill", async () => {
                    await api.createSkill(skill);
                    setSkill(EMPTY_SKILL);
                  });
                }}
              >
                <input
                  className="field"
                  placeholder="skill_name"
                  value={skill.name}
                  onChange={(event) => setSkill({ ...skill, name: event.target.value })}
                />
                <input
                  className="field"
                  placeholder="Short description"
                  value={skill.description}
                  onChange={(event) => setSkill({ ...skill, description: event.target.value })}
                />
                <textarea
                  className="field min-h-[72px]"
                  placeholder="Instruction the model should follow"
                  value={skill.body}
                  onChange={(event) => setSkill({ ...skill, body: event.target.value })}
                />
                <button className="btn" disabled={busy === "skill" || !skill.name.trim() || !skill.body.trim()}>
                  Add skill
                </button>
              </form>
            </article>

            <article className="panel p-4">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-[14px] font-medium">MCP servers</h2>
                <button className="btn-primary px-3 py-1.5 text-[12px]" disabled={busy === "demo"} onClick={() => run("demo", () => api.demoMcp())}>
                  {busy === "demo" ? "Connecting" : "Use local demo"}
                </button>
              </div>
              <p className="mt-1 text-[12px] leading-5 text-mute">
                Probe a stdio or HTTP server. Connected tools are added to the model allow-list.
              </p>
              <ul className="mt-3 space-y-2">
                {view.mcp.length === 0 && (
                  <li className="rounded-xl border border-dashed border-white/10 px-3 py-6 text-center text-[12px] text-faint">
                    No servers yet. Start with the local demo.
                  </li>
                )}
                {view.mcp.map((item) => (
                  <ServerCard
                    key={item.id}
                    server={item}
                    busy={busy}
                    onProbe={() => run(item.id, () => api.probeMcp(item.id))}
                    onToggle={() => run(item.id, () => api.updateMcp(item.id, { enabled: !item.enabled }))}
                    onRemove={() => run(item.id, () => api.deleteMcp(item.id))}
                  />
                ))}
              </ul>
              <form
                className="mt-3 space-y-2 border-t border-white/8 pt-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  run("mcp", async () => {
                    await api.createMcp({
                      name: server.name,
                      transport: server.transport,
                      command: server.command,
                      args: server.args.trim() ? server.args.trim().split(/\s+/) : [],
                      url: server.url,
                      enabled: false,
                    });
                    setServer(EMPTY_SERVER);
                  });
                }}
              >
                <input
                  className="field"
                  placeholder="server_name"
                  value={server.name}
                  onChange={(event) => setServer({ ...server, name: event.target.value })}
                />
                <select
                  className="field"
                  value={server.transport}
                  onChange={(event) => setServer({ ...server, transport: event.target.value })}
                >
                  <option value="stdio">stdio</option>
                  <option value="http">http</option>
                </select>
                {server.transport === "stdio" ? (
                  <>
                    <input
                      className="field"
                      placeholder="Command, e.g. python"
                      value={server.command}
                      onChange={(event) => setServer({ ...server, command: event.target.value })}
                    />
                    <input
                      className="field"
                      placeholder="Args, e.g. -m forge.mcp_demo"
                      value={server.args}
                      onChange={(event) => setServer({ ...server, args: event.target.value })}
                    />
                  </>
                ) : (
                  <input
                    className="field"
                    placeholder="https://example.com/mcp"
                    value={server.url}
                    onChange={(event) => setServer({ ...server, url: event.target.value })}
                  />
                )}
                <button className="btn" disabled={busy === "mcp" || !server.name.trim()}>
                  Add server
                </button>
              </form>
            </article>
          </section>
        </>
      )}
    </div>
  );
}

function ServerCard({
  server,
  busy,
  onProbe,
  onToggle,
  onRemove,
}: {
  server: McpServer;
  busy: string;
  onProbe: () => void;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const tone = server.status === "connected" ? "text-ok" : server.status === "failed" ? "text-bad" : "text-faint";
  const endpoint = server.transport === "http" ? server.url : [server.command, ...(server.args || [])].filter(Boolean).join(" ");
  return (
    <li className="rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`status-dot ${tone}`} />
            <span className="font-mono text-[12px]">{server.name}</span>
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-faint">
            {server.transport} · {server.status}
            {endpoint ? ` · ${endpoint}` : ""}
          </div>
        </div>
      </div>
      {server.error && <p className="mt-1.5 text-[12px] leading-5 text-bad">{server.error}</p>}
      {server.tools.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {server.tools.map((tool) => (
            <span key={tool.prompt_name} className="chip chip-on font-mono" title={tool.description}>
              {tool.prompt_name}
            </span>
          ))}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        <button className="btn px-2 py-1 text-[11px]" disabled={busy === server.id} onClick={onProbe}>
          Probe
        </button>
        <button className={`chip ${server.enabled ? "chip-on" : ""}`} disabled={busy === server.id} onClick={onToggle}>
          {server.enabled ? "Enabled" : "Disabled"}
        </button>
        <button className="btn-ghost px-2 py-1 text-[11px]" onClick={onRemove}>
          Remove
        </button>
      </div>
    </li>
  );
}
