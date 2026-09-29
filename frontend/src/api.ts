async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  repos: () => request<import("./types").Repo[]>("/api/repos"),
  connectRepo: (body: Record<string, string>) =>
    request<import("./types").Repo>("/api/repos", { method: "POST", body: JSON.stringify(body) }),
  indexRepo: (id: string) => request<{ stats: Record<string, unknown> }>(`/api/repos/${id}/index`, { method: "POST" }),
  searchKg: (id: string, q: string) =>
    request<{ hits: { kind: string; qualname: string; file: string; signature: string }[]; pack: string }>(
      `/api/repos/${id}/kg/search?q=${encodeURIComponent(q)}`,
    ),
  configs: () => request<import("./types").ForgeConfig[]>("/api/configs"),
  saveConfig: (name: string, body: import("./types").ForgeConfig) =>
    request<import("./types").ForgeConfig>(`/api/configs/${name}`, { method: "PUT", body: JSON.stringify(body) }),
  runs: () => request<import("./types").Run[]>("/api/runs"),
  run: (id: string) => request<import("./types").Run>(`/api/runs/${id}`),
  createRun: (body: { repo_id: string; config: string; goal: string; llm?: Record<string, string> }) =>
    request<import("./types").Run>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  resume: (id: string, note: string) =>
    request<import("./types").Run>(`/api/runs/${id}/resume`, { method: "POST", body: JSON.stringify({ note }) }),
  providers: () => request<import("./types").ProviderInfo[]>("/api/providers"),
  providerHealth: (body: Record<string, string>) =>
    request<{ provider: string; ok: boolean; detail: string }>("/api/providers/health", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  benchTasks: () => request<import("./types").BenchTask[]>("/api/benchmarks/tasks"),
  benchmarks: () => request<import("./types").Benchmark[]>("/api/benchmarks"),
  benchmark: (id: string) => request<import("./types").Benchmark>(`/api/benchmarks/${id}`),
  runBenchmark: (body: { repo_id: string; configs: string[]; task_ids: string[] }) =>
    request<import("./types").Benchmark>("/api/benchmarks", { method: "POST", body: JSON.stringify(body) }),
  studio: (config = "full_forge") =>
    request<import("./types").StudioSnapshot>(`/api/studio?config=${encodeURIComponent(config)}`),
  createSkill: (body: { name: string; description?: string; body: string; enabled?: boolean }) =>
    request<import("./types").Skill>("/api/skills", { method: "POST", body: JSON.stringify(body) }),
  updateSkill: (id: string, body: { name?: string; description?: string; body?: string; enabled?: boolean }) =>
    request<import("./types").Skill>(`/api/skills/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteSkill: (id: string) => request<{ ok: boolean }>(`/api/skills/${id}`, { method: "DELETE" }),
  createMcp: (body: {
    name: string;
    transport: string;
    command?: string;
    args?: string[];
    url?: string;
    enabled?: boolean;
  }) => request<import("./types").McpServer>("/api/mcp", { method: "POST", body: JSON.stringify(body) }),
  updateMcp: (
    id: string,
    body: { name?: string; transport?: string; command?: string; args?: string[]; url?: string; enabled?: boolean },
  ) => request<import("./types").McpServer>(`/api/mcp/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteMcp: (id: string) => request<{ ok: boolean }>(`/api/mcp/${id}`, { method: "DELETE" }),
  probeMcp: (id: string) => request<import("./types").McpServer>(`/api/mcp/${id}/probe`, { method: "POST" }),
  demoMcp: () => request<import("./types").McpServer>("/api/mcp/demo", { method: "POST" }),
};
