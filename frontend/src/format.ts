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

export function statusTone(status: string): string {
  if (status === "completed" || status === "done") return "text-ok border-ok/40";
  if (status === "failed") return "text-bad border-bad/40";
  if (status === "completed_with_failures") return "text-brass border-brass/40";
  if (status === "awaiting_human") return "text-info border-info/40";
  if (status === "running" || status === "planning") return "text-brass border-brass/50";
  return "text-mute border-line";
}
