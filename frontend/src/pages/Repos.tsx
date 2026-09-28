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

  async function refresh() {
    setRepos(await api.repos());
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
    try {
      await api.indexRepo(id);
      setActive(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "index failed");
    }
  }

  async function search() {
    if (!active) return;
    const result = await api.searchKg(active, query);
    setPack(result.pack || result.hits.map((hit) => `${hit.kind} ${hit.qualname}`).join("\n"));
  }

  return (
    <div className="space-y-6">
      <header>
        <div className="kicker">Repository</div>
        <h1 className="font-display text-4xl">Connect a codebase</h1>
        <p className="mt-2 max-w-2xl text-sm text-mute">
          Local folders and GitHub repositories, public or private with a token. Indexing builds the file, symbol,
          module, dependency, and test graph that small models query when the prompt is full.
        </p>
      </header>
      <section className="panel p-4">
        <div className="flex gap-2 text-sm">
          {["local", "github"].map((item) => (
            <button
              key={item}
              className={`rounded border px-3 py-1 ${source === item ? "border-brass text-brass" : "border-line text-mute"}`}
              onClick={() => setSource(item)}
            >
              {item}
            </button>
          ))}
        </div>
        {source === "local" ? (
          <input
            className="mt-3 w-full rounded border border-line bg-black/30 px-3 py-2 font-mono text-sm"
            placeholder="/absolute/path/to/examples/todo_api"
            value={path}
            onChange={(event) => setPath(event.target.value)}
          />
        ) : (
          <div className="mt-3 grid gap-2">
            <input className="rounded border border-line bg-black/30 px-3 py-2 text-sm" placeholder="https://github.com/org/repo" value={url} onChange={(event) => setUrl(event.target.value)} />
            <input className="rounded border border-line bg-black/30 px-3 py-2 text-sm" placeholder="GitHub token (private repos)" type="password" value={token} onChange={(event) => setToken(event.target.value)} />
          </div>
        )}
        <input className="mt-2 w-full rounded border border-line bg-black/30 px-3 py-2 text-sm" placeholder="Display name (optional)" value={name} onChange={(event) => setName(event.target.value)} />
        <button className="mt-3 rounded bg-brass px-4 py-2 text-sm text-black" onClick={connect}>
          Connect
        </button>
        {error && <p className="mt-2 text-sm text-bad">{error}</p>}
      </section>
      <section className="grid gap-3">
        {repos.map((repo) => (
          <article key={repo.id} className={`panel p-4 ${active === repo.id ? "shadow-insetbrass" : ""}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-lg">{repo.name}</div>
                <div className="font-mono text-xs text-mute">{repo.source === "github" ? repo.url : repo.path}</div>
                <div className="mt-2 text-xs text-mute">
                  {repo.indexed_at ? `indexed ${repo.indexed_at}` : "not indexed"}
                  {repo.kg_stats?.nodes ? ` · ${repo.kg_stats.nodes} nodes · ${repo.kg_stats.edges} edges` : ""}
                  {repo.token_set ? " · token stored" : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <button className="rounded border border-line px-3 py-1 text-sm" onClick={() => index(repo.id)}>
                  Index graph
                </button>
                <button className="rounded border border-line px-3 py-1 text-sm" onClick={() => setActive(repo.id)}>
                  Select
                </button>
              </div>
            </div>
          </article>
        ))}
      </section>
      {active && (
        <section className="panel p-4">
          <div className="kicker">Graph query</div>
          <div className="mt-2 flex gap-2">
            <input className="flex-1 rounded border border-line bg-black/30 px-3 py-2 text-sm" value={query} onChange={(event) => setQuery(event.target.value)} />
            <button className="rounded bg-brass px-3 py-2 text-sm text-black" onClick={search}>
              Retrieve
            </button>
          </div>
          <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs text-mute">{pack}</pre>
        </section>
      )}
    </div>
  );
}
