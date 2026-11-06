import { Background, BackgroundVariant, Controls, Edge, Node, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { useCatalogue } from "../lib/auth";
import type { Definition, ExecStatus, NodeRun } from "../lib/types";
import { FlowNodeData, nodeTypes } from "./FlowNode";

export function runsByNode(runs: NodeRun[]): Record<string, FlowNodeData["run"]> {
  const out: Record<string, NonNullable<FlowNodeData["run"]>> = {};
  for (const run of runs) {
    const current = out[run.node_id];
    if (!current) {
      out[run.node_id] = { status: run.status, duration_ms: run.duration_ms, simulated: run.simulated, count: run.status === "skipped" ? 0 : 1 };
    } else {
      // A loop body runs repeatedly: a failure wins, an executed run beats a skip.
      current.count = (current.count || 0) + (run.status === "skipped" ? 0 : 1);
      current.duration_ms = (current.duration_ms || 0) + (run.duration_ms || 0);
      current.simulated = current.simulated || run.simulated;
      if (run.status === "failed" || run.status === "running" || current.status === "skipped") current.status = run.status;
    }
  }
  return out;
}

export function edgeStyle(sourceStatus?: ExecStatus, targetStatus?: ExecStatus, port?: string): Partial<Edge> {
  const ran = sourceStatus && !["skipped", "pending"].includes(sourceStatus) && targetStatus && targetStatus !== "skipped";
  if (!ran) return sourceStatus ? { style: { stroke: "#2c3a51", strokeDasharray: "4 4" } } : port === "error" ? { style: { stroke: "#EF444499" } } : {};
  if (targetStatus === "failed") return { style: { stroke: "#EF4444", strokeWidth: 2 } };
  if (targetStatus === "running") return { className: "edge-running", style: { stroke: "#818CF8", strokeWidth: 2 } };
  return { style: { stroke: "#22C55E", strokeWidth: 2 } };
}

function Inner({ definition, runs, onNodeClick, selectedNodeId, showControls }: { definition: Definition; runs?: NodeRun[]; onNodeClick?: (id: string) => void; selectedNodeId?: string | null; showControls?: boolean }) {
  const { byType } = useCatalogue();
  const statuses = useMemo(() => (runs ? runsByNode(runs) : {}), [runs]);
  const nodes = useMemo<Node[]>(
    () =>
      definition.nodes.map((n) => ({
        id: n.id,
        type: "flow",
        position: n.position,
        selected: n.id === selectedNodeId,
        data: { name: n.name, nodeType: n.type, config: n.config, settings: n.settings, spec: byType[n.type], run: statuses[n.id] || null } as FlowNodeData,
      })),
    [definition, byType, statuses, selectedNodeId],
  );
  const edges = useMemo<Edge[]>(
    () =>
      definition.edges.map((e) => ({
        id: e.id,
        source: e.source,
        sourceHandle: e.source_port,
        target: e.target,
        targetHandle: e.target_port || "main",
        ...edgeStyle(statuses[e.source]?.status, statuses[e.target]?.status, e.source_port),
      })),
    [definition, statuses],
  );
  return (
    <ReactFlow
      key={Object.keys(byType).length}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
      minZoom={0.2}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={!!onNodeClick}
      onNodeClick={(_e, node) => onNodeClick?.(node.id)}
      proOptions={{ hideAttribution: !showControls }}
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="#223048" />
      {showControls && <Controls showInteractive={false} className="!shadow-none [&_button]:!border-line [&_button]:!bg-surface [&_button]:!fill-muted" />}
    </ReactFlow>
  );
}

export function WorkflowPreview(props: { definition: Definition; runs?: NodeRun[]; onNodeClick?: (id: string) => void; selectedNodeId?: string | null; showControls?: boolean; className?: string }) {
  return (
    <div className={props.className || "h-64"} style={{ background: "#0C1422" }}>
      <ReactFlowProvider>
        <Inner {...props} />
      </ReactFlowProvider>
    </div>
  );
}
