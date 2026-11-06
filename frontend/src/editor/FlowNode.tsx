import { Handle, NodeProps, Position } from "@xyflow/react";
import {
  AlertTriangle,
  ArrowRightLeft,
  Ban,
  Braces,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Filter,
  FlaskConical,
  GitBranch,
  Globe,
  Hourglass,
  Loader2,
  LucideIcon,
  Mail,
  Merge,
  MinusCircle,
  Play,
  Repeat,
  Scale,
  ScanText,
  Send,
  ShieldCheck,
  Sparkles,
  Split,
  Table,
  Tags,
  TextSearch,
  Variable,
  Wand2,
  Webhook,
  XCircle,
} from "lucide-react";
import { memo } from "react";
import { cx } from "../components/ui";
import { duration } from "../lib/format";
import type { ExecStatus, NodeSettings, NodeSpec } from "../lib/types";
import { outputPorts } from "./graph";

export const ICONS: Record<string, LucideIcon> = {
  play: Play,
  webhook: Webhook,
  clock: Clock,
  "git-branch": GitBranch,
  split: Split,
  filter: Filter,
  merge: Merge,
  hourglass: Hourglass,
  repeat: Repeat,
  variable: Variable,
  wand: Wand2,
  braces: Braces,
  table: Table,
  "text-search": TextSearch,
  "arrow-right-left": ArrowRightLeft,
  "shield-check": ShieldCheck,
  sparkles: Sparkles,
  tags: Tags,
  "file-text": FileText,
  "scan-text": ScanText,
  scale: Scale,
  globe: Globe,
  send: Send,
  mail: Mail,
  database: Database,
};

export const CATEGORY: Record<string, { label: string; tile: string; dot: string }> = {
  trigger: { label: "Triggers", tile: "bg-trigger-soft text-[#FBBF24]", dot: "#F59E0B" },
  logic: { label: "Logic", tile: "bg-cyan-soft text-cyan", dot: "#22D3EE" },
  data: { label: "Data", tile: "bg-primary-soft text-[#A5A7F8]", dot: "#6366F1" },
  ai: { label: "AI", tile: "bg-ai-soft text-[#B9A0FA]", dot: "#8B5CF6" },
  integration: { label: "Integrations", tile: "bg-action-soft text-[#93C5FD]", dot: "#3B82F6" },
};

export interface FlowNodeData extends Record<string, unknown> {
  name: string;
  nodeType: string;
  description?: string;
  config: Record<string, any>;
  settings?: NodeSettings;
  spec?: NodeSpec;
  run?: { status: ExecStatus; duration_ms?: number | null; simulated?: boolean; count?: number } | null;
  issues?: { errors: number; warnings: number };
}

const RUN_RING: Partial<Record<ExecStatus, string>> = {
  completed: "border-success/70",
  failed: "border-danger shadow-[0_0_0_1px_#EF4444]",
  running: "border-primary shadow-[0_0_0_1px_#6366F1]",
  waiting: "border-cyan/70",
  cancelled: "border-warning/70",
};

function RunIcon({ status }: { status: ExecStatus }) {
  if (status === "completed") return <CheckCircle2 size={14} className="text-success" aria-label="Completed" />;
  if (status === "failed") return <XCircle size={14} className="text-danger" aria-label="Failed" />;
  if (status === "running") return <Loader2 size={14} className="animate-spin text-primary-hover" aria-label="Running" />;
  if (status === "waiting") return <Hourglass size={14} className="text-cyan" aria-label="Waiting" />;
  if (status === "cancelled") return <Ban size={14} className="text-warning" aria-label="Cancelled" />;
  if (status === "skipped") return <MinusCircle size={14} className="text-faint" aria-label="Skipped" />;
  return null;
}

export const FlowNode = memo(function FlowNode({ data, selected }: NodeProps) {
  const d = data as FlowNodeData;
  const spec = d.spec;
  const Icon = (spec && ICONS[spec.icon]) || Braces;
  const category = CATEGORY[spec?.category || "data"];
  const ports = outputPorts(spec, d.config || {}, d.settings);
  const multiple = ports.length > 1 || (ports[0] && ports[0].label && spec?.category === "logic");
  const skipped = d.run?.status === "skipped";

  return (
    <div
      className={cx(
        "w-[232px] rounded-lg border bg-surface shadow-node transition-[border-color,box-shadow,opacity]",
        selected ? "border-primary shadow-[0_0_0_1px_#6366F1]" : d.run ? RUN_RING[d.run.status] || "border-line" : "border-line hover:border-lineStrong",
        skipped && "opacity-45",
      )}
      data-testid={`node-${d.name}`}
    >
      {spec && spec.inputs.length > 0 && <Handle type="target" position={Position.Left} id="main" aria-label="Input" style={{ top: 24 }} />}
      <div className="flex items-center gap-2.5 px-2.5 py-2">
        <div className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-md", category.tile)}>
          <Icon size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold leading-tight text-ink">{d.name}</div>
          <div className="truncate text-2xs text-faint">{spec?.label || `Unknown: ${d.nodeType}`}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {d.issues && d.issues.errors > 0 && <AlertTriangle size={14} className="text-warning" aria-label={`${d.issues.errors} problems`} />}
          {d.run && <RunIcon status={d.run.status} />}
        </div>
      </div>
      {d.run && (d.run.duration_ms !== undefined || d.run.simulated) && d.run.status !== "skipped" && (
        <div className="flex items-center justify-between border-t border-line/70 px-2.5 py-1 text-2xs text-muted">
          <span className="tabular">
            {duration(d.run.duration_ms)}
            {d.run.count && d.run.count > 1 ? ` · ${d.run.count} runs` : ""}
          </span>
          {d.run.simulated && (
            <span className="flex items-center gap-1 text-cyan">
              <FlaskConical size={10} /> Simulated
            </span>
          )}
        </div>
      )}
      {multiple ? (
        <div className="border-t border-line/70 py-1">
          {ports.map((port) => (
            <div key={port.id} className="relative flex h-[22px] items-center justify-end pr-3 text-2xs text-muted">
              <span className={cx("max-w-[190px] truncate", port.id === "error" && "text-[#F87171]")}>{port.label || port.id}</span>
              <Handle type="source" position={Position.Right} id={port.id} aria-label={`Output ${port.label || port.id}`} style={port.id === "error" ? { borderColor: "#EF4444" } : undefined} />
            </div>
          ))}
        </div>
      ) : (
        ports[0] && <Handle type="source" position={Position.Right} id={ports[0].id} aria-label="Output" style={{ top: 24 }} />
      )}
    </div>
  );
});

export const nodeTypes = { flow: FlowNode };
