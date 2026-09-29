export function fmtRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

export function fmtMs(value?: number | null): string {
  if (!value) return "0s";
  const seconds = Math.round(value / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function elapsedSince(iso?: string | null, ended?: string | null): number {
  if (!iso) return 0;
  const start = Date.parse(iso);
  const end = ended ? Date.parse(ended) : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return 0;
  return Math.max(0, end - start);
}

export function isLive(status: string): boolean {
  return ["queued", "planning", "running", "awaiting_human"].includes(status);
}

export function statusTone(status: string): string {
  if (status === "completed" || status === "done") return "text-ok border-ok/30 bg-ok/10";
  if (status === "failed") return "text-bad border-bad/30 bg-bad/10";
  if (status === "completed_with_failures") return "text-accent border-accent/30 bg-accent/10";
  if (status === "awaiting_human") return "text-info border-info/30 bg-info/10";
  if (status === "running" || status === "planning" || status === "queued") return "text-accent border-accent/40 bg-accent/10";
  return "text-mute border-white/10 bg-white/[0.04]";
}

export function fmtWhen(iso?: string | null): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(then).toLocaleString();
}
