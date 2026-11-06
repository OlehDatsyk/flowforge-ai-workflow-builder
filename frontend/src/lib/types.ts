export interface Port {
  id: string;
  label: string;
  data_type: "any" | "object" | "array";
}
export interface FieldSpec {
  key: string;
  label: string;
  type: "string" | "text" | "number" | "boolean" | "select" | "json" | "expression" | "keyvalue" | "rows" | "credential" | "string_list";
  required: boolean;
  default: any;
  help: string;
  placeholder: string;
  options?: { value: any; label: string }[];
  columns?: FieldSpec[];
  credential_types?: string[];
  visible_if?: Record<string, any[]>;
  min?: number;
  max?: number;
}
export interface NodeSpec {
  type: string;
  label: string;
  category: "trigger" | "logic" | "data" | "ai" | "integration";
  description: string;
  icon: string;
  is_trigger: boolean;
  multi_input: boolean;
  dynamic_outputs: boolean;
  inputs: Port[];
  outputs: Port[];
  fields: FieldSpec[];
  input_schema: any;
  output_schema: any;
  defaults: Record<string, any>;
  requires_integration: string | null;
}
export interface NodeSettings {
  retry?: { max_attempts: number; delay_ms: number; backoff: number; allow_non_idempotent: boolean };
  timeout_seconds?: number;
  on_error?: "stop" | "continue" | "error_branch";
}
export interface DefNode {
  id: string;
  type: string;
  name: string;
  description?: string;
  position: { x: number; y: number };
  config: Record<string, any>;
  settings?: NodeSettings;
}
export interface DefEdge {
  id: string;
  source: string;
  source_port: string;
  target: string;
  target_port: string;
}
export interface Definition {
  schema_version: number;
  nodes: DefNode[];
  edges: DefEdge[];
}
export interface Issue {
  code: string;
  message: string;
  node_id?: string | null;
  edge_id?: string | null;
  field?: string | null;
}
export interface Validation {
  valid: boolean;
  errors: Issue[];
  warnings: Issue[];
}
export interface Workflow {
  id: string;
  name: string;
  description: string;
  category: string;
  folder: string;
  tags: string[];
  is_active: boolean;
  is_demo: boolean;
  revision: number;
  node_count: number;
  node_types: string[];
  created_at: string;
  updated_at: string;
  runs?: number;
  failures?: number;
  last_run_at?: string | null;
  definition?: Definition;
  validation?: Validation;
  latest_version?: number | null;
  active_version?: number | null;
}
export type ExecStatus = "pending" | "running" | "waiting" | "completed" | "failed" | "cancelled" | "skipped";
export interface ExecutionSummary {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: ExecStatus;
  mode: "run" | "test";
  trigger_type: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  nodes_executed: number;
  error: string | null;
  error_type: string | null;
  retry_of_id: string | null;
  is_demo: boolean;
}
export interface NodeRun {
  id: string;
  node_id: string;
  node_name: string;
  node_type: string;
  sequence: number;
  iteration: number | null;
  status: ExecStatus;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  input: any;
  output: any;
  error: string | null;
  error_type: string | null;
  simulated: boolean;
  ai_provider: string | null;
  ai_input_tokens: number | null;
  ai_output_tokens: number | null;
}
export interface ExecutionDetail extends ExecutionSummary {
  version: number;
  version_id: string;
  definition: Definition;
  failed_node_id: string | null;
  trigger_data: any;
  result: any;
  retry_ids: string[];
  can_retry: boolean;
  can_cancel: boolean;
  has_side_effects: boolean;
  nodes: NodeRun[];
}
export interface User {
  id: string;
  email: string;
  name: string;
  is_demo: boolean;
  csrf_token: string;
  workspaces: { id: string; name: string; role: string }[];
}
export interface Proposal {
  status: "ready" | "invalid" | "rejected" | "no_change";
  feasible: boolean;
  analysis: { summary?: string; triggers?: string[]; processing?: string[]; conditions?: string[]; integrations?: string[] };
  unsupported_requirements: string[];
  required_setup: string[];
  changes: string[];
  notes: string[];
  workflow: { name: string; description: string; definition: Definition | null };
  validation: Validation;
  provider: string;
  model: string;
  is_demo: boolean;
  usage: { input_tokens?: number; output_tokens?: number };
  conversation_id: string;
  diff?: {
    added_nodes: { id: string; name: string; type: string }[];
    removed_nodes: { id: string; name: string; type: string }[];
    changed_nodes: { id: string; name: string; type: string }[];
    added_edges: number;
    removed_edges: number;
  };
}
export const TERMINAL: ExecStatus[] = ["completed", "failed", "cancelled"];
