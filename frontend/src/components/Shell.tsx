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

const SIDEBAR_KEY = "forge-sidebar";

function routeOf(hash: string): string {
  const route = hash.split("?")[0] || "#/";
  if (route === "#/customize") return "#/studio";
  if (route === "#/settings") return "#/providers";
  return route;
}

export default function Shell({ hash, children }: { hash: string; children: ReactNode }) {
  const route = routeOf(hash);
  const title = route.startsWith("#/runs/") ? "Run" : TITLES[route] || "FORGE";
  const [open, setOpen] = useState(false);
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 767px)").matches);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === "collapsed");
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
    const query = window.matchMedia("(max-width: 767px)");
    const onChange = () => setNarrow(query.matches);
    onChange();
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
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

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      localStorage.setItem(SIDEBAR_KEY, next ? "collapsed" : "open");
      return next;
    });
  }

  const rail = collapsed && !narrow;
  const selected = configs.find((item) => item.name === configName) || configs.find((item) => item.name === "full_forge") || configs[0];
  const provider = selected?.llm?.provider || "mock";
  const model = selected?.llm?.model || "mock-small";
  const host = hostOf(selected?.llm?.base_url);
  const activeRuns = runs.filter((run) => isLive(run.status));
  const earlier = runs.filter((run) => !isLive(run.status)).slice(0, 8);

  return (
    <div className="app-frame" data-collapsed={rail ? "true" : "false"}>
      {open && (
        <button className="drawer-back" aria-label="Close menu" onClick={() => setOpen(false)} />
      )}
      <aside className={`side ${open ? "is-open" : ""}`}>
        <div className="logo-row">
          <a href="#/" className="brand" title="FORGE">
            <Mark />
            <span className="brand-copy">FORGE</span>
          </a>
          <button
            className="icon-btn only-wide"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleCollapsed}
          >
            <Icon name="panel" />
          </button>
        </div>
        <a href="#/" className="new-session" title="New session">
          <Icon name="plus" />
          <span>New session</span>
        </a>
        <nav className="flex flex-col gap-0.5" aria-label="Primary">
          {NAV.map((item) => {
            const active = item.href === "#/" ? route === "#/" || route === "" : route.startsWith(item.href);
            return (
              <a key={item.href} href={item.href} className={`nav-link ${active ? "active" : ""}`} title={item.label}>
                <Icon name={item.icon} />
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>
        <div className="side-scroll mt-3">
          {activeRuns.length > 0 && <RunGroup label="Active" runs={activeRuns} current={route} />}
          <RunGroup label="Sessions" runs={earlier} current={route} empty="No sessions yet" />
        </div>
        <div className="side-foot">
          <a href="#/settings" className={`nav-link ${route.startsWith("#/providers") ? "active" : ""}`} title="Settings">
            <Icon name="settings" />
            <span>Settings</span>
          </a>
        </div>
      </aside>
      <div className="center">
        <header className="center-bar">
          <div className="flex min-w-0 items-center gap-2">
            <button className="icon-btn only-narrow" aria-label="Open menu" onClick={() => setOpen(true)}>
              <Icon name="menu" />
            </button>
            <div className="truncate text-[13px] font-medium">{title}</div>
          </div>
          <div className="flex min-w-0 items-center gap-2 text-[11px] text-faint" title={selected ? `${selected.name} environment` : "Environment"}>
            <span className="rounded-md border border-line bg-elevated px-1.5 py-0.5 font-mono text-mute">{host}</span>
            <span className="hidden truncate font-mono sm:inline">
              {provider} / {model}
            </span>
          </div>
        </header>
        <main className="center-body">
          <div key={route} className="page-enter mx-auto max-w-6xl">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

function RunGroup({ label, runs, empty, current }: { label: string; runs: Run[]; empty?: string; current: string }) {
  return (
    <div className="mb-3">
      <div className="session-label">{label}</div>
      {runs.length === 0 && empty && <p className="px-2 py-1 text-[12px] text-faint">{empty}</p>}
      <ul className="mt-1 space-y-0.5">
        {runs.map((run) => {
          const href = `#/runs/${run.id}`;
          const active = current === href;
          return (
            <li key={run.id}>
              <a href={href} className={`session-link ${active ? "active" : ""}`} title={run.goal}>
                {isLive(run.status) && <span className="status-dot is-live mr-2 inline-block align-middle text-accent" />}
                {run.goal.replace(/\s+/g, " ").slice(0, 48)}
              </a>
            </li>
          );
        })}
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

function Mark() {
  return (
    <span className="mark" aria-hidden>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <path d="M3 11.5 8 4l5 7.5" />
        <path d="M5.2 11.5h5.6" />
      </svg>
    </span>
  );
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
  if (name === "plus") {
    return (
      <svg {...common}>
        <path d="M12 5v14M5 12h14" />
      </svg>
    );
  }
  if (name === "panel") {
    return (
      <svg {...common}>
        <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
        <path d="M9 4.5v15" />
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
