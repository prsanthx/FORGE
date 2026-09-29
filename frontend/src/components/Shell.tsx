import type { ReactNode } from "react";

const NAV = [
  { href: "#/", label: "Agents", icon: "agents" },
  { href: "#/studio", label: "Studio", icon: "studio" },
  { href: "#/repos", label: "Repositories", icon: "repo" },
  { href: "#/configs", label: "Configs", icon: "sliders" },
  { href: "#/benchmarks", label: "Benchmarks", icon: "grid" },
  { href: "#/providers", label: "Providers", icon: "bolt" },
];

const TITLES: Record<string, string> = {
  "#/": "Agents",
  "#/studio": "Studio",
  "#/repos": "Repositories",
  "#/configs": "Configs",
  "#/benchmarks": "Benchmarks",
  "#/providers": "Providers",
};

export default function Shell({ hash, children }: { hash: string; children: ReactNode }) {
  const route = hash.split("?")[0] || "#/";
  const title = route.startsWith("#/runs/") ? "Run" : TITLES[route] || "FORGE";
  return (
    <div className="min-h-screen md:grid md:grid-cols-[228px_1fr]">
      <aside className="flex flex-col border-b border-white/8 bg-black/20 px-3 py-4 backdrop-blur md:sticky md:top-0 md:h-screen md:border-b-0 md:border-r md:py-5">
        <a href="#/" className="flex items-center gap-2.5 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-white text-[13px] font-semibold text-black shadow-lift">
            F
          </span>
          <span>
            <span className="block text-[13px] font-semibold tracking-tight">FORGE</span>
            <span className="block text-[11px] text-faint">Reliable agent harness</span>
          </span>
        </a>
        <nav className="mt-5 flex gap-1 overflow-x-auto md:mt-6 md:flex-col">
          {NAV.map((item) => {
            const active = item.href === "#/" ? route === "#/" || route === "" : route.startsWith(item.href);
            return (
              <a key={item.href} href={item.href} className={`nav-link shrink-0 ${active ? "active" : ""}`}>
                <Icon name={item.icon} />
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="mt-auto hidden px-2 pt-6 md:block">
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <div className="flex items-center gap-2 text-[12px] text-ink">
              <span className="status-dot text-ok" />
              Local harness
            </div>
            <p className="mt-1.5 text-[11px] leading-5 text-faint">
              Plan, verify, and recover. The deliverable is a tested branch.
            </p>
          </div>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-white/8 bg-[#09090b]/75 px-5 py-3 backdrop-blur-xl md:px-8">
          <div className="text-[13px] font-medium text-mute">{title}</div>
          <div className="flex items-center gap-2 text-[11px] text-faint">
            <span className="rounded-md border border-white/10 bg-white/[0.03] px-1.5 py-0.5 font-mono">127.0.0.1</span>
            MockLLM
          </div>
        </header>
        <main className="min-w-0 px-5 py-6 md:px-8 md:py-7">
          <div key={route} className="page-enter mx-auto max-w-6xl">
            {children}
          </div>
        </main>
      </div>
    </div>
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
  if (name === "agents") {
    return (
      <svg {...common}>
        <path d="M12 3l1.6 4.2L18 9l-4.4 1.8L12 15l-1.6-4.2L6 9l4.4-1.8L12 3z" />
        <path d="M18 14l.7 1.8L20.5 17l-1.8.7L18 19.5l-.7-1.8L15.5 17l1.8-.7L18 14z" />
      </svg>
    );
  }
  if (name === "studio") {
    return (
      <svg {...common}>
        <path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h5A1.5 1.5 0 0 1 16 5.5V7" />
        <rect x="4" y="7" width="16" height="12" rx="2" />
        <path d="M9 12h6M12 9v6" />
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
  return (
    <svg {...common}>
      <path d="M13 3L6 13h5l-1 8 8-12h-5l0-6z" />
    </svg>
  );
}
