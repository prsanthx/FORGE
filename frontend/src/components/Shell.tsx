import type { ReactNode } from "react";

const NAV = [
  ["#/", "Dashboard"],
  ["#/repos", "Repos"],
  ["#/configs", "Configs"],
  ["#/benchmarks", "Benchmarks"],
  ["#/providers", "Providers"],
];

export default function Shell({ hash, children }: { hash: string; children: ReactNode }) {
  const route = hash.split("?")[0] || "#/";
  return (
    <div className="grid min-h-screen grid-cols-[232px_1fr]">
      <aside className="border-r border-line bg-black/25 px-4 py-6">
        <a href="#/" className="block px-2">
          <div className="font-display text-3xl tracking-wide text-brass">FORGE</div>
          <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-mute">Fault-resilient engineering</div>
        </a>
        <div className="mt-8 h-px bg-gradient-to-r from-brass/70 to-transparent" />
        <nav className="mt-6 flex flex-col gap-1">
          {NAV.map(([href, label]) => {
            const active = href === "#/" ? route === "#/" || route === "" : route.startsWith(href);
            return (
              <a
                key={href}
                href={href}
                className={`rounded px-3 py-2 text-sm ${active ? "bg-brass/15 text-brass" : "text-ink/80 hover:bg-white/5"}`}
              >
                {label}
              </a>
            );
          })}
        </nav>
        <p className="mt-10 px-2 text-xs leading-5 text-mute">
          Planning, verification, and recovery for small models. A branch is the deliverable, not a snippet.
        </p>
      </aside>
      <main className="min-w-0 px-8 py-7">{children}</main>
    </div>
  );
}
