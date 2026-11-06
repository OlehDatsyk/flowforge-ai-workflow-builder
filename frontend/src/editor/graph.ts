/** Pure workflow-graph helpers shared by the editor, previews and tests. */
import type { DefEdge, DefNode, Definition, NodeSettings, NodeSpec, Port } from "../lib/types";

export const DEFAULT_SETTINGS: Required<NodeSettings> = {
  retry: { max_attempts: 1, delay_ms: 1000, backoff: 2, allow_non_idempotent: false },
  timeout_seconds: 30,
  on_error: "stop",
};

export function outputPorts(spec: NodeSpec | undefined, config: Record<string, any>, settings?: NodeSettings): Port[] {
  if (!spec) return [{ id: "main", label: "", data_type: "any" }];
  let ports = spec.outputs;
  if (spec.type === "logic.switch") {
    const cases: any[] = Array.isArray(config.cases) ? config.cases : [];
    ports = [
      ...cases.map((c, i) => ({ id: `case_${i}`, label: String(c?.label || c?.equals || `Case ${i + 1}`).slice(0, 40), data_type: "any" as const })),
      { id: "default", label: "Default", data_type: "any" as const },
    ];
  }
  if (settings?.on_error === "error_branch") ports = [...ports, { id: "error", label: "Error", data_type: "object" }];
  return ports;
}

export function wouldCreateCycle(edges: Pick<DefEdge, "source" | "target">[], source: string, target: string): boolean {
  const next: Record<string, string[]> = {};
  for (const e of edges) (next[e.source] ||= []).push(e.target);
  const stack = [target];
  const seen = new Set<string>();
  while (stack.length) {
    const current = stack.pop()!;
    if (current === source) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(next[current] || []));
  }
  return false;
}

export interface ConnectionCheck {
  ok: boolean;
  reason?: string;
}

/** Fast client check for drag feedback. The backend validator stays authoritative. */
export function checkConnection(
  nodes: Pick<DefNode, "id" | "type" | "config" | "settings" | "name">[],
  edges: DefEdge[],
  byType: Record<string, NodeSpec>,
  connection: { source: string | null; target: string | null; sourceHandle?: string | null },
): ConnectionCheck {
  const { source, target } = connection;
  if (!source || !target) return { ok: false };
  if (source === target) return { ok: false, reason: "A node cannot connect to itself" };
  const from = nodes.find((n) => n.id === source);
  const to = nodes.find((n) => n.id === target);
  if (!from || !to) return { ok: false };
  const toSpec = byType[to.type];
  const fromSpec = byType[from.type];
  if (toSpec?.is_trigger) return { ok: false, reason: `${to.name} is a trigger and cannot receive connections` };
  const port = connection.sourceHandle || "main";
  if (edges.some((e) => e.source === source && e.source_port === port && e.target === target)) return { ok: false, reason: "These nodes are already connected" };
  if (wouldCreateCycle(edges, source, target)) return { ok: false, reason: "That would create a cycle. Use a Loop node to repeat steps." };
  const out = outputPorts(fromSpec, from.config, from.settings).find((p) => p.id === port);
  const input = toSpec?.inputs[0];
  if (out && input && out.data_type !== "any" && input.data_type !== "any" && out.data_type !== input.data_type) {
    return { ok: false, reason: `${from.name} outputs a ${out.data_type} but ${to.name} needs an ${input.data_type}` };
  }
  return { ok: true };
}

export function uniqueName(base: string, existing: string[]): string {
  if (!existing.includes(base)) return base;
  let i = 2;
  while (existing.includes(`${base} ${i}`)) i++;
  return `${base} ${i}`;
}

export function newNodeId(type: string): string {
  const stem = type.split(".").pop()!.replace(/[^a-z0-9]/gi, "_");
  return `${stem}_${Math.random().toString(36).slice(2, 8)}`;
}

export function createNode(spec: NodeSpec, position: { x: number; y: number }, existingNames: string[]): DefNode {
  return {
    id: newNodeId(spec.type),
    type: spec.type,
    name: uniqueName(spec.label, existingNames),
    description: "",
    position,
    config: JSON.parse(JSON.stringify(spec.defaults)),
    settings: JSON.parse(JSON.stringify(DEFAULT_SETTINGS)),
  };
}

export function isFieldVisible(field: { visible_if?: Record<string, any[]> }, config: Record<string, any>, spec: NodeSpec): boolean {
  if (!field.visible_if) return true;
  return Object.entries(field.visible_if).every(([key, allowed]) => allowed.includes(config[key] ?? spec.defaults[key]));
}

export function emptyDefinition(): Definition {
  return { schema_version: 1, nodes: [], edges: [] };
}
