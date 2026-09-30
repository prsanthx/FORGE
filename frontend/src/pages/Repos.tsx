import { useEffect, useState } from "react";
import { api } from "../api";
import type { Repo } from "../types";

export default function Repos() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [source, setSource] = useState("local");
  const [path, setPath] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [pack, setPack] = useState("");
  const [query, setQuery] = useState("TodoStore add");
  const [active, setActive] = useState<string>("");
  const [indexing, setIndexing] = useState("");

  async function refresh() {
    const rows = await api.repos();
    setRepos(rows);
    setActive((current) => current || rows.find((repo) => repo.indexed_at)?.id || rows[0]?.id || "");
  }
  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, []);

  async function connect() {
    setError("");
    try {
      const body: Record<string, string> = { source, name };
      if (source === "github") {
        body.url = url;
        body.token = token;
      } else {
        body.path = path;
      }
      const repo = await api.connectRepo(body);
      setActive(repo.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "connect failed");
    }
  }

  async function index(id: string) {
    setError("");
    setIndexing(id);
    try {
      await api.indexRepo(id);
      setActive(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "index failed");
    } finally {
      setIndexing("");
    }
  }

  async function search() {
    if (!active) return;
    const result = await api.searchKg(active, query);
    setPack(result.pack || result.hits.map((hit) => `${hit.kind} ${hit.qualname}`).join("\n"));
  }

  const selected = repos.find((repo) => repo.id === active);

  return (
    <div className="stagger space-y-6">
      <header>
        <div className="kicker">Knowledge graph</div>
        <h1 className="mt-1 text-[26px] font-semibold tracking-tight">Repositories</h1>
        <p className="mt-2 max-w-2xl text-[13px] leading-6 text-mute">
          Local folders and GitHub repositories. Indexing builds the file, symbol, module, dependency, and test graph the model queries when the prompt is full.
        </p>
      </header>

      <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="composer p-4">
          <div className="seg w-full">
            {["local", "github"].map((item) => (
              <button
                key={item}
                className="flex-1 capitalize"
                aria-pressed={source === item}
                onClick={() => setSource(item)}
              >
                {item}
              </button>
            ))}
          </div>
          {source === "local" ? (
            <input
              className="field mt-3 font-mono text-[12px]"
              placeholder="/absolute/path/to/examples/todo_api"
              value={path}
              onChange={(event) => setPath(event.target.value)}
            />
          ) : (
            <div className="mt-3 grid gap-2">
              <input className="field" placeholder="https://github.com/org/repo" value={url} onChange={(event) => setUrl(event.target.value)} />
              <input className="field" placeholder="GitHub token for private repos" type="password" value={token} onChange={(event) => setToken(event.target.value)} />
            </div>
          )}
          <input className="field mt-2" placeholder="Display name (optional)" value={name} onChange={(event) => setName(event.target.value)} />
          <div className="mt-3 flex items-center gap-3">
            <button className="btn-primary" onClick={connect}>Connect</button>
            {error && <p className="text-[12px] text-bad">{error}</p>}
          </div>
        </div>

        <div className="space-y-2">
          {repos.length === 0 && (
            <div className="panel px-4 py-8 text-center text-sm text-mute">Connect a local folder or a GitHub repository.</div>
          )}
          {repos.map((repo) => (
            <article key={repo.id} className={`panel panel-hover p-4 ${active === repo.id ? "border-accent/40" : ""}`}>
              <div className="flex items-start justify-between gap-3">
                <button className="min-w-0 text-left" onClick={() => setActive(repo.id)}>
                  <div className="text-[15px] font-medium">{repo.name}</div>
                  <div className="mt-1 truncate font-mono text-[11px] text-faint">{repo.source === "github" ? repo.url : repo.path}</div>
                </button>
                <button className="btn-ghost shrink-0" onClick={() => index(repo.id)} disabled={indexing === repo.id}>
                  {indexing === repo.id ? "Indexing" : "Index"}
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-mute">
                <span className={`chip ${repo.indexed_at ? "chip-on" : ""}`}>{repo.indexed_at ? "Indexed" : "Not indexed"}</span>
                {repo.kg_stats?.nodes ? <span className="chip">{repo.kg_stats.nodes} nodes</span> : null}
                {repo.kg_stats?.edges ? <span className="chip">{repo.kg_stats.edges} edges</span> : null}
                {repo.token_set ? <span className="chip">Token stored</span> : null}
              </div>
            </article>
          ))}
          <p className="px-1 text-[11px] text-faint">Removing a repository is not available from this screen.</p>
        </div>
      </section>

      {selected && (
        <section className="panel p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="kicker">Context pack</div>
              <div className="mt-1 text-[15px] font-medium">{selected.name}</div>
            </div>
            <div className="flex min-w-[280px] flex-1 gap-2">
              <input className="field" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") search(); }} />
              <button className="btn-primary" onClick={search}>Retrieve</button>
            </div>
          </div>
          {selected.kg_stats?.kinds && (
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {Object.entries(selected.kg_stats.kinds).map(([kind, count]) => (
                <div key={kind} className="rounded-lg bg-elevated px-3 py-2">
                  <div className="text-[11px] capitalize text-faint">{kind}</div>
                  <div className="text-lg font-semibold">{count}</div>
                </div>
              ))}
            </div>
          )}
          <pre className="codeblock mt-4 max-h-72 text-[11px]">{pack || "Ask the graph for a symbol, file, or behavior."}</pre>
        </section>
      )}
    </div>
  );
}
