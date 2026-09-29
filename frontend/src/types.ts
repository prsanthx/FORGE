export type Repo = {
  id: string;
  name: string;
  source: string;
  path: string;
  url?: string;
  token_set: boolean;
  indexed_at?: string | null;
  kg_stats?: { nodes?: number; edges?: number; kinds?: Record<string, number> };
  created_at: string;
};

export type FeatureFlags = Record<string, boolean>;

export type ForgeConfig = {
  name: string;
  description?: string;
  features: FeatureFlags;
  verification?: { levels?: string[]; fail_fast?: boolean };
  recovery?: { max_retries?: number; risk_threshold?: number; strategies?: string[] };
  executor?: { max_steps_per_task?: number; context_char_budget?: number };
  llm?: { provider?: string; model?: string; base_url?: string | null; temperature?: number };
  tools?: { enabled?: string[] };
};

export type Task = {
  id: string;
  task_key: string;
  title: string;
  description: string;
  dependencies: string[];
  expected_output: string;
  failure_conditions: string[];
  phase: string;
  status: string;
  attempt: number;
  summary?: string;
  elapsed_ms?: number;
};

export type LlmCall = {
  id: string;
  task_id?: string | null;
  provider: string;
  model: string;
  phase: string;
  prompt_preview: string;
  response_preview: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  created_at: string;
};

export type ToolCall = {
  id: string;
  task_id?: string | null;
  name: string;
  args: string;
  result_preview: string;
  ok: number;
  elapsed_ms: number;
  created_at: string;
};

export type Metrics = {
  tokens_in?: number;
  tokens_out?: number;
  tokens?: number;
  llm_calls?: number;
  tool_calls?: number;
  elapsed_ms?: number;
  verification_pass_rate?: number | null;
  recovery_success?: number | null;
  human_intervention?: boolean;
  tasks_total?: number;
  tasks_done?: number;
  tasks_failed?: number;
};

export type Run = {
  id: string;
  repo_id: string;
  config_name: string;
  goal: string;
  status: string;
  workspace?: string;
  branch?: string;
  started_at?: string;
  ended_at?: string;
  metrics: Metrics;
  error?: string;
  human_question?: string;
  plan?: { summary?: string; phases?: { id: string; title: string; task_ids: string[] }[] };
  tasks?: Task[];
  llm_calls?: LlmCall[];
  tool_calls?: ToolCall[];
  failures?: { task_key: string; failure_class: string; strategy: string; attempt: number; resolved: number }[];
};

export type RunEvent = {
  id: number;
  kind: string;
  created_at: string;
  payload: { message?: string; status?: string; [key: string]: unknown };
};

export type BenchTask = { id: string; difficulty: string; title: string; prompt: string };

export type BenchCell = {
  config_name: string;
  task_id: string;
  difficulty: string;
  run_id: string;
  metrics: Record<string, number | string | null>;
};

export type Benchmark = {
  id: string;
  status: string;
  created_at: string;
  cells?: BenchCell[];
};

export type ProviderInfo = {
  provider: string;
  model: string;
  base_url: string;
  api_key_env: string;
};

export type BuiltinTool = {
  name: string;
  group: string;
  summary: string;
  enabled: boolean;
  always: boolean;
};

export type Skill = {
  id: string;
  name: string;
  description: string;
  body: string;
  enabled: boolean;
  created_at: string;
};

export type McpTool = {
  name: string;
  prompt_name: string;
  description: string;
};

export type McpServer = {
  id: string;
  name: string;
  transport: string;
  command: string;
  args: string[];
  url: string;
  enabled: boolean;
  status: string;
  tools: McpTool[];
  error: string;
  created_at: string;
};

export type StudioSummary = {
  builtin_enabled: number;
  finish: number;
  mcp_tools: number;
  skills_enabled: number;
  tools_in_prompt: number;
};

export type StudioSnapshot = {
  config: string;
  builtin: BuiltinTool[];
  skills: Skill[];
  mcp: McpServer[];
  prompt_tools: string[];
  summary: StudioSummary;
};
