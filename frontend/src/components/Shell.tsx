import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { isLive } from "../format";
import { applyTheme, readSelectedConfig, readTheme } from "../theme";
import type { ForgeConfig, Run } from "../types";

const NAV = [
  { href: "#/", label: "Sessions", icon: "sessions" },
  { href: "#/studio", label: "Customize", icon: "customize" },
  { href: "#/repos", label: "Repositories", icon: "repo" },
  { href: "#/configs", label: "Configs", icon: "sliders" },
  { href: "#/benchmarks", label: "Benchmarks", icon: "grid" },
];

const TITLES: Record<string, string> = {
  "#/": "Sessions",
  "#/studio": "Customize",
  "#/customize": "Customize",
  "#/repos": "Repositories",
  "#/configs": "Configs",
  "#/benchmarks": "Benchmarks",
  "#/providers": "Settings",
  "#/settings": "Settings",
};

function routeOf(hash: string): string {
  const route = hash.split("?")[0] || "#/";
  if (route === "#/customize") return "#/studio";
  if (route === "#/settings") return "#/providers";
  return route;
}

export default function Shell({ hash, children }: { hash: string; children: ReactNode }) {
  const route = routeOf(hash);
  const title = route.startsWith("#/runs/") ? "Run" : TITLES[route] || TITLES[hash.split("?")[0]] || "FORGE";
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<Run[]>([]);
  const [configs, setConfigs] = useState<ForgeConfig[]>([]);
  const [configName, setConfigName] = useState(readSelectedConfig());

  useEffect(() => {
    applyTheme(readTheme());
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onTheme = () => applyTheme(readTheme());
    media.addEventListener("change", onTheme);
    window.addEventListener("forge-theme", onTheme);
    return () => {
      media.removeEventListener("change", onTheme);
      window.removeEventListener("forge-theme", onTheme);
    };
  }, []);

  useEffect(() => {
    const load = () => {
      api.runs().then(setRuns).catch(() => undefined);
      api.configs().then(setConfigs).catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 5000);
    const onConfig = () => setConfigName(readSelectedConfig());
    window.addEventListener("forge-config", onConfig);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("forge-config", onConfig);
    };
  }, []);

  useEffect(() => {
    setOpen(false);
  }, [hash]);

  const selected = configs.find((item) => item.name === configName) || configs.find((item) => item.name === "full_forge") || configs[0];
  const provider = selected?.llm?.provider || "mock";
  const model = selected?.llm?.model || "mock-small";
  const host = hostOf(selected?.llm?.base_url);
  const activeRuns = runs.filter((run) => isLive(run.status));
  const earlier = runs.filter((run) => !isLive(run.status)).slice(0, 6);

  return (
    <div className="min-h-screen md:grid md:grid-cols-[248px_1fr]">
      {open && (
        <button className="fixed inset-0 z-30 bg-ink/30 md:hidden" aria-label="Close menu" onClick={() => setOpen(false)} />
      )}
      <aside
        className={`${open ? "flex" : "hidden"} fixed inset-y-0 left-0 z-40 w-[248px] flex-col border-r border-line bg-sidebar px-3 py-4 md:sticky md:top-0 md:flex md:h-screen`}
      >
        <a href="#/" className="flex items-center gap-2.5 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-ink text-[13px] font-semibold text-canvas">F</span>
          <span>
            <span className="block text-[13px] font-semibold tracking-tight">FORGE</span>
            <span className="block text-[11px] text-faint">Reliable agent harness</span>
          </span>
        </a>
        <a href="#/" className="btn-primary mt-4 w-full">
          New session
        </a>
        <nav className="mt-4 flex flex-col gap-0.5">
          {NAV.map((item) => {
            const active = item.href === "#/" ? route === "#/" || route === "" : route.startsWith(item.href);
            return (
              <a key={item.href} href={item.href} className={`nav-link ${active ? "active" : ""}`}>
                <Icon name={item.icon} />
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-auto px-1">
          {activeRuns.length > 0 && (
            <RunGroup label="Active" runs={activeRuns} />
          )}
          <RunGroup label="Earlier" runs={earlier} empty="No sessions yet" />
        </div>
        <div className="mt-3 border-t border-line pt-3">
          <a href="#/settings" className={`nav-link ${route.startsWith("#/providers") ? "active" : ""}`}>
            <Icon name="settings" />
            Settings
          </a>
          <div className="mt-2 rounded-xl border border-line bg-panel px-3 py-2.5">
            <div className="flex items-center gap-2 text-[12px] text-ink">
              <span className="status-dot text-ok" />
              Local harness
            </div>
            <p className="mt-1 text-[11px] leading-5 text-faint">
              Plan, verify, and recover. The deliverable is a tested branch.
            </p>
          </div>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-line bg-canvas/90 px-4 py-3 backdrop-blur md:px-8">
          <div className="flex items-center gap-2">
            <button className="btn px-2 py-1 md:hidden" aria-label="Open menu" onClick={() => setOpen(true)}>
              <Icon name="menu" />
            </button>
            <div className="text-[13px] font-medium">{title}</div>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-faint" title={selected ? `${selected.name} environment` : "Environment"}>
            <span className="rounded-md border border-line bg-panel px-1.5 py-0.5 font-mono">{host}</span>
            <span className="font-mono">
              {provider} / {model}
            </span>
          </div>
        </header>
        <main className="min-w-0 px-4 py-6 md:px-8 md:py-7">
          <div key={route} className="page-enter mx-auto max-w-6xl">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

function RunGroup({ label, runs, empty }: { label: string; runs: Run[]; empty?: string }) {
  return (
    <div>
      <div className="px-1.5 text-[10px] font-medium uppercase tracking-wider text-faint">{label}</div>
      {runs.length === 0 && empty && <p className="px-1.5 py-1 text-[12px] text-faint">{empty}</p>}
      <ul className="mt-1 space-y-0.5">
        {runs.map((run) => (
          <li key={run.id}>
            <a href={`#/runs/${run.id}`} className="block truncate rounded-md px-1.5 py-1 text-[12px] text-mute hover:bg-elevated hover:text-ink">
              {run.goal.replace(/\s+/g, " ").slice(0, 42)}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function hostOf(baseUrl?: string | null): string {
  if (!baseUrl) return "local";
  try {
    return new URL(baseUrl).host || baseUrl;
  } catch {
    return baseUrl;
  }
}

function Icon({ name }: { name: string }) {
  const common = {
    viewBox: "0 0 24 24",
    className: "h-4 w-4",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (name === "sessions") {
    return (
      <svg {...common}>
        <path d="M5 6.5h14M5 12h14M5 17.5h9" />
      </svg>
    );
  }
  if (name === "customize") {
    return (
      <svg {...common}>
        <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
        <circle cx="12" cy="12" r="3.2" />
      </svg>
    );
  }
  if (name === "repo") {
    return (
      <svg {...common}>
        <path d="M4 7.5A2.5 2.5 0 0 1 6.5 5H10l2 2h5.5A2.5 2.5 0 0 1 20 9.5v7A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5v-9z" />
      </svg>
    );
  }
  if (name === "sliders") {
    return (
      <svg {...common}>
        <path d="M4 8h10M18 8h2M4 16h2M10 16h10" />
        <circle cx="16" cy="8" r="2" />
        <circle cx="8" cy="16" r="2" />
      </svg>
    );
  }
  if (name === "grid") {
    return (
      <svg {...common}>
        <rect x="4" y="4" width="6" height="6" rx="1.2" />
        <rect x="14" y="4" width="6" height="6" rx="1.2" />
        <rect x="4" y="14" width="6" height="6" rx="1.2" />
        <rect x="14" y="14" width="6" height="6" rx="1.2" />
      </svg>
    );
  }
  if (name === "menu") {
    return (
      <svg {...common}>
        <path d="M4 7h16M4 12h16M4 17h16" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3V20.5M3.5 12h2.2M18.3 12H20.5M6 6l1.6 1.6M16.4 16.4 18 18M18 6l-1.6 1.6M7.6 16.4 6 18" />
    </svg>
  );
}
