import {
  addEdge,
  Background,
  BackgroundVariant,
  Connection,
  Edge,
  MiniMap,
  Node,
  OnSelectionChangeParams,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  useViewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  CircleCheck,
  CloudOff,
  FlaskConical,
  History,
  Layers,
  LayoutGrid,
  Loader2,
  Maximize,
  Minus,
  Play,
  Plus,
  Power,
  Redo2,
  Search,
  Sparkles,
  Square,
  Undo2,
} from "lucide-react";
import { DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge, Button, cx, DemoBadge, EmptyState, ErrorState, Notice, SimulatedBadge, Skeleton, StatusBadge, Tabs, Tip, useFeedback } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { useAuth, useCatalogue } from "../lib/auth";
import { duration } from "../lib/format";
import { useIsNarrow } from "../lib/hooks";
import { DefEdge, DefNode, Definition, ExecutionDetail, Issue, NodeSpec, TERMINAL, Validation, Workflow } from "../lib/types";
import { AIAssistant } from "./AIAssistant";
import { CATEGORY, FlowNodeData, ICONS, nodeTypes } from "./FlowNode";
import { checkConnection, createNode, DEFAULT_SETTINGS, newNodeId, uniqueName } from "./graph";
import { NodePanel, VersionsModal } from "./NodePanel";
import { edgeStyle, runsByNode, WorkflowPreview } from "./WorkflowPreview";
import { NodeRunRow } from "../pages/ExecutionDetail";

type RFNode = Node<FlowNodeData>;
type SaveState = "saved" | "dirty" | "saving" | "error";
type Snapshot = { nodes: RFNode[]; edges: Edge[] };

function toFlow(definition: Definition, byType: Record<string, NodeSpec>): Snapshot {
  return {
    nodes: definition.nodes.map((n) => ({
      id: n.id,
      type: "flow",
      position: n.position,
      data: { name: n.name, nodeType: n.type, description: n.description, config: n.config, settings: n.settings, spec: byType[n.type] },
    })),
    edges: definition.edges.map((e) => ({ id: e.id, source: e.source, sourceHandle: e.source_port, target: e.target, targetHandle: e.target_port || "main", ...edgeStyle(undefined, undefined, e.source_port) })),
  };
}

function toDefinition(nodes: RFNode[], edges: Edge[]): Definition {
  return {
    schema_version: 1,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      name: n.data.name,
      description: n.data.description || "",
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
      config: n.data.config,
      settings: { ...DEFAULT_SETTINGS, ...(n.data.settings || {}) },
    })),
    edges: edges.map((e): DefEdge => ({ id: e.id, source: e.source, source_port: e.sourceHandle || "main", target: e.target, target_port: e.targetHandle || "main" })),
  };
}

const clean = (s: Snapshot): Snapshot => ({
  nodes: s.nodes.map(({ selected: _s, dragging: _d, ...n }) => ({ ...n, data: { ...n.data, run: undefined } })) as RFNode[],
  edges: s.edges.map(({ selected: _s, ...e }) => e),
});

function NodeLibrary({ specs, onAdd, disabled }: { specs: NodeSpec[]; onAdd: (spec: NodeSpec) => void; disabled: boolean }) {
  const [query, setQuery] = useState("");
  const groups = ["trigger", "logic", "data", "ai", "integration"];
  const q = query.trim().toLowerCase();
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line p-2">
        <div className="relative">
          <Search size={13} className="absolute left-2 top-2 text-faint" />
          <input aria-label="Search nodes" className="field pl-7" placeholder="Search nodes" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {groups.map((group) => {
          const items = specs.filter((s) => s.category === group && (!q || s.label.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)));
          if (!items.length) return null;
          return (
            <div key={group} className="mb-3">
              <div className="mb-1 px-1 text-2xs font-semibold uppercase tracking-wide text-faint">{CATEGORY[group].label}</div>
              <div className="space-y-0.5">
                {items.map((spec) => {
                  const Icon = ICONS[spec.icon];
                  return (
                    <button
                      key={spec.type}
                      draggable={!disabled}
                      disabled={disabled}
                      title={spec.description}
                      data-testid={`lib-${spec.type}`}
                      onDragStart={(e) => {
                        e.dataTransfer.setData("application/flowforge-node", spec.type);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onClick={() => onAdd(spec)}
                      className="flex w-full cursor-grab items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-raised active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className={cx("flex h-6 w-6 shrink-0 items-center justify-center rounded", CATEGORY[group].tile)}>{Icon && <Icon size={13} />}</span>
                      <span className="truncate text-xs font-medium">{spec.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ZoomControls() {
  const flow = useReactFlow();
  const { zoom } = useViewport();
  return (
    <div className="flex items-center rounded-md border border-line bg-raised">
      <Tip text="Zoom out">
        <button aria-label="Zoom out" className="flex h-[30px] w-7 items-center justify-center text-muted hover:text-ink" onClick={() => flow.zoomOut({ duration: 120 })}>
          <Minus size={14} />
        </button>
      </Tip>
      <span className="tabular w-10 text-center text-2xs text-muted" data-testid="zoom-level">
        {Math.round(zoom * 100)}%
      </span>
      <Tip text="Zoom in">
        <button aria-label="Zoom in" className="flex h-[30px] w-7 items-center justify-center text-muted hover:text-ink" onClick={() => flow.zoomIn({ duration: 120 })}>
          <Plus size={14} />
        </button>
      </Tip>
      <Tip text="Fit to screen">
        <button aria-label="Fit to screen" className="flex h-[30px] w-7 items-center justify-center border-l border-line text-muted hover:text-ink" onClick={() => flow.fitView({ padding: 0.15, duration: 160, maxZoom: 1.1 })}>
          <Maximize size={13} />
        </button>
      </Tip>
    </div>
  );
}

function SaveIndicator({ state }: { state: SaveState }) {
  const map = {
    saved: { icon: <CircleCheck size={13} className="text-success" />, text: "Saved" },
    dirty: { icon: <span className="h-1.5 w-1.5 rounded-full bg-warning" />, text: "Unsaved" },
    saving: { icon: <Loader2 size={13} className="animate-spin" />, text: "Saving" },
    error: { icon: <CloudOff size={13} className="text-danger" />, text: "Not saved" },
  }[state];
  return (
    <span className="flex items-center gap-1.5 text-2xs text-muted" data-testid="save-state" role="status">
      {map.icon}
      {map.text}
    </span>
  );
}

function EditorInner({ workflow: initial, reload }: { workflow: Workflow; reload: () => void }) {
  const { byType, specs } = useCatalogue();
  const { canEdit, user, workspaceId } = useAuth();
  const { toast, confirm } = useFeedback();
  const flow = useReactFlow();
  const workspaceName = user?.workspaces.find((w) => w.id === workspaceId)?.name;

  const first = useMemo(() => toFlow(initial.definition!, byType), [initial, byType]);
  const [nodes, setNodes, onNodesChange] = useNodesState<RFNode>(first.nodes as RFNode[]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(first.edges);
  const [name, setName] = useState(initial.name);
  const [isActive, setIsActive] = useState(initial.is_active);
  const [activeVersion, setActiveVersion] = useState(initial.active_version);
  const [selection, setSelection] = useState<string[]>([]);
  const [validation, setValidation] = useState<Validation | null>(initial.validation || null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [panel, setPanel] = useState<"node" | "ai">("node");
  const [aiOpen, setAiOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [consoleTab, setConsoleTab] = useState<"run" | "problems">("run");
  const [execution, setExecution] = useState<ExecutionDetail | null>(null);
  const [busy, setBusy] = useState<"run" | "test" | "publish" | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  // ---- history
  const past = useRef<Snapshot[]>([]);
  const future = useRef<Snapshot[]>([]);
  const [, bump] = useState(0);
  const lastRecord = useRef(0);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  nodesRef.current = nodes;
  edgesRef.current = edges;

  const record = useCallback((coalesce = false) => {
    const now = Date.now();
    if (coalesce && now - lastRecord.current < 800) return;
    lastRecord.current = now;
    past.current = [...past.current.slice(-79), clean({ nodes: nodesRef.current, edges: edgesRef.current })];
    future.current = [];
    bump((v) => v + 1);
  }, []);

  const restore = useCallback(
    (from: React.MutableRefObject<Snapshot[]>, to: React.MutableRefObject<Snapshot[]>) => {
      const snapshot = from.current[from.current.length - 1];
      if (!snapshot) return;
      from.current = from.current.slice(0, -1);
      to.current = [...to.current, clean({ nodes: nodesRef.current, edges: edgesRef.current })];
      setNodes(snapshot.nodes);
      setEdges(snapshot.edges);
      bump((v) => v + 1);
    },
    [setNodes, setEdges],
  );
  const undo = useCallback(() => restore(past, future), [restore]);
  const redo = useCallback(() => restore(future, past), [restore]);

  // ---- saving
  const definition = useMemo(() => toDefinition(nodes, edges), [nodes, edges]);
  const serialized = useMemo(() => JSON.stringify(definition), [definition]);
  const savedRef = useRef(JSON.stringify(toDefinition(first.nodes as RFNode[], first.edges)));
  const revision = useRef(initial.revision);
  const inflight = useRef<Promise<void> | null>(null);
  const latest = useRef(serialized);
  latest.current = serialized;

  const save = useCallback(async (): Promise<void> => {
    if (inflight.current) await inflight.current;
    const body = latest.current;
    if (body === savedRef.current) return;
    setSaveState("saving");
    const work = (async () => {
      const result = await api<Workflow>(`/api/workflows/${initial.id}`, { method: "PUT", body: { definition: JSON.parse(body), revision: revision.current } });
      revision.current = result.revision;
      savedRef.current = body;
      setValidation(result.validation || null);
      setSaveState(latest.current === body ? "saved" : "dirty");
    })();
    inflight.current = work.finally(() => (inflight.current = null));
    try {
      await work;
    } catch (exc) {
      setSaveState("error");
      toast(exc instanceof ApiError ? exc.message : "Could not save", "error");
      throw exc;
    }
  }, [initial.id, toast]);

  useEffect(() => {
    if (!canEdit) return;
    if (serialized === savedRef.current) {
      // An edit that was undone back to the saved state leaves nothing to save.
      setSaveState((state) => (state === "dirty" ? "saved" : state));
      return;
    }
    setSaveState("dirty");
    const id = setTimeout(() => save().catch(() => undefined), 900);
    return () => clearTimeout(id);
  }, [serialized, save, canEdit]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (latest.current !== savedRef.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  // ---- node issues
  const issuesByNode = useMemo(() => {
    const out: Record<string, Issue[]> = {};
    for (const issue of validation?.errors || []) if (issue.node_id) (out[issue.node_id] ||= []).push(issue);
    return out;
  }, [validation]);

  const runs = useMemo(() => (execution ? runsByNode(execution.nodes) : null), [execution]);

  const displayNodes = useMemo(
    () => nodes.map((n) => ({ ...n, data: { ...n.data, run: runs?.[n.id] ?? null, issues: { errors: issuesByNode[n.id]?.length || 0, warnings: 0 } } })),
    [nodes, runs, issuesByNode],
  );
  const displayEdges = useMemo(() => (runs ? edges.map((e) => ({ ...e, ...edgeStyle(runs[e.source]?.status, runs[e.target]?.status, e.sourceHandle || undefined) })) : edges), [edges, runs]);

  // ---- editing actions
  const addNode = useCallback(
    (spec: NodeSpec, position?: { x: number; y: number }) => {
      if (!canEdit) return;
      record();
      const current = nodesRef.current;
      const rightmost = current.reduce((max, n) => Math.max(max, n.position.x), -240);
      const at = position || { x: rightmost + 300, y: current.length ? current[current.length - 1].position.y : 200 };
      const node = createNode(spec, at, current.map((n) => n.data.name));
      const created: RFNode = { id: node.id, type: "flow", position: at, selected: true, data: { name: node.name, nodeType: node.type, description: "", config: node.config, settings: node.settings, spec } };
      setNodes([...current.map((n) => ({ ...n, selected: false })), created]);
      setPanel("node");
      if (!position) requestAnimationFrame(() => flow.fitView({ padding: 0.2, duration: 200, maxZoom: 1 }));
    },
    [canEdit, record, setNodes, flow],
  );

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const spec = byType[e.dataTransfer.getData("application/flowforge-node")];
      if (spec) addNode(spec, flow.screenToFlowPosition({ x: e.clientX - 116, y: e.clientY - 24 }));
    },
    [byType, addNode, flow],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const check = checkConnection(toDefinition(nodesRef.current, []).nodes, toDefinition([], edgesRef.current).edges, byType, connection);
      if (!check.ok) {
        if (check.reason) toast(check.reason, "error");
        return;
      }
      record();
      const id = `e_${connection.source}_${connection.sourceHandle || "main"}_${connection.target}`;
      setEdges((all) => addEdge({ ...connection, id, ...edgeStyle(undefined, undefined, connection.sourceHandle || undefined) }, all));
    },
    [byType, record, setEdges, toast],
  );

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => {
      const check = checkConnection(toDefinition(nodesRef.current, []).nodes, toDefinition([], edgesRef.current).edges, byType, connection);
      setHint(check.ok ? null : check.reason || null);
      return check.ok;
    },
    [byType],
  );

  const duplicate = useCallback(
    (ids: string[]) => {
      if (!ids.length || !canEdit) return;
      record();
      const current = nodesRef.current;
      const names = current.map((n) => n.data.name);
      const mapping: Record<string, string> = {};
      const copies: RFNode[] = current
        .filter((n) => ids.includes(n.id))
        .map((n) => {
          const id = newNodeId(n.data.nodeType);
          mapping[n.id] = id;
          const copyName = uniqueName(`${n.data.name} copy`, names);
          names.push(copyName);
          return { ...n, id, selected: true, position: { x: n.position.x + 48, y: n.position.y + 64 }, data: { ...JSON.parse(JSON.stringify({ ...n.data, spec: undefined, run: undefined })), spec: n.data.spec, name: copyName } };
        });
      const edgeCopies = edgesRef.current
        .filter((e) => ids.includes(e.source) && ids.includes(e.target))
        .map((e) => ({ ...e, selected: false, id: `e_${mapping[e.source]}_${e.sourceHandle}_${mapping[e.target]}`, source: mapping[e.source], target: mapping[e.target] }));
      setNodes([...current.map((n) => ({ ...n, selected: false })), ...copies]);
      setEdges([...edgesRef.current, ...edgeCopies]);
    },
    [canEdit, record, setNodes, setEdges],
  );

  const removeNodes = useCallback(
    (ids: string[]) => {
      if (!ids.length || !canEdit) return;
      record();
      setNodes((all) => all.filter((n) => !ids.includes(n.id)));
      setEdges((all) => all.filter((e) => !ids.includes(e.source) && !ids.includes(e.target)));
    },
    [canEdit, record, setNodes, setEdges],
  );

  const patchNode = useCallback(
    (id: string, patch: Partial<DefNode>) => {
      record(true);
      setNodes((all) =>
        all.map((n) => {
          if (n.id !== id) return n;
          const data = { ...n.data };
          if (patch.name !== undefined) data.name = patch.name;
          if (patch.description !== undefined) data.description = patch.description;
          if (patch.config) data.config = patch.config;
          if (patch.settings) data.settings = patch.settings;
          return { ...n, data };
        }),
      );
      if (patch.settings?.on_error && patch.settings.on_error !== "error_branch") {
        setEdges((all) => all.filter((e) => !(e.source === id && e.sourceHandle === "error")));
      }
    },
    [record, setNodes, setEdges],
  );

  const autoLayout = useCallback(async () => {
    record();
    const laid = await api<Definition>("/api/definitions/layout", { method: "POST", body: { definition: toDefinition(nodesRef.current, edgesRef.current) } });
    const positions = Object.fromEntries(laid.nodes.map((n) => [n.id, n.position]));
    setNodes((all) => all.map((n) => ({ ...n, position: positions[n.id] || n.position })));
    requestAnimationFrame(() => flow.fitView({ padding: 0.15, duration: 200, maxZoom: 1 }));
  }, [record, setNodes, flow]);

  const applyProposal = useCallback(
    (next: Definition) => {
      record();
      const snapshot = toFlow(next, byType);
      setNodes(snapshot.nodes as RFNode[]);
      setEdges(snapshot.edges);
      requestAnimationFrame(() => flow.fitView({ padding: 0.15, duration: 200, maxZoom: 1 }));
    },
    [record, byType, setNodes, setEdges, flow],
  );

  // ---- keyboard
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        redo();
      } else if (mod && e.key.toLowerCase() === "d") {
        e.preventDefault();
        duplicate(nodesRef.current.filter((n) => n.selected).map((n) => n.id));
      } else if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        save().catch(() => undefined);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [undo, redo, duplicate, save]);

  // ---- running
  const watching = useRef<string | null>(null);
  const watch = useCallback((id: string) => {
    watching.current = id;
    setConsoleOpen(true);
    setConsoleTab("run");
    const poll = async () => {
      if (watching.current !== id) return;
      try {
        const data = await api<ExecutionDetail>(`/api/executions/${id}`);
        if (watching.current !== id) return;
        setExecution(data);
        if (!TERMINAL.includes(data.status)) setTimeout(poll, 500);
      } catch {
        setTimeout(poll, 1500);
      }
    };
    poll();
  }, []);

  useEffect(() => {
    const handler = (e: Event) => watch((e as CustomEvent<string>).detail);
    window.addEventListener("ff-watch-execution", handler);
    return () => {
      window.removeEventListener("ff-watch-execution", handler);
      watching.current = null;
    };
  }, [watch]);

  const run = async (mode: "run" | "test") => {
    setBusy(mode);
    try {
      await save();
      const external = definition.nodes
        .filter((n) => {
          const c = { ...byType[n.type]?.defaults, ...n.config };
          return n.type === "integration.email" || n.type === "integration.webhook_send" || (n.type === "integration.http" && c.method !== "GET") || (n.type === "integration.database" && ["insert", "update", "delete"].includes(c.operation));
        })
        .map((n) => n.name);
      if (mode === "run" && external.length) {
        const ok = await confirm({
          title: "Run with real actions?",
          body: (
            <>
              This run performs real actions, including <b className="text-ink">{external.join(", ")}</b>. Use <b className="text-ink">Test</b> to simulate them instead.
            </>
          ),
          confirm: "Run for real",
        });
        if (!ok) return;
      }
      const result = await api(`/api/workflows/${initial.id}/run`, { method: "POST", body: { mode } });
      toast(mode === "test" ? "Test started. External actions are simulated." : "Run started", "info");
      setExecution(null);
      watch(result.execution_id);
    } catch (exc) {
      if (exc instanceof ApiError) {
        toast(exc.message, "error");
        if (exc.issues.length) {
          setConsoleOpen(true);
          setConsoleTab("problems");
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const togglePublish = async () => {
    setBusy("publish");
    try {
      await save();
      if (isActive) {
        await api(`/api/workflows/${initial.id}/deactivate`, { method: "POST" });
        setIsActive(false);
        toast("Workflow deactivated. Its triggers no longer fire.", "info");
      } else {
        const ok = await confirm({ title: "Publish and activate?", body: "Webhook and schedule triggers will start running this version, including its real external actions.", confirm: "Publish" });
        if (!ok) return;
        await api(`/api/workflows/${initial.id}/activate`, { method: "POST" });
        const fresh = await api<Workflow>(`/api/workflows/${initial.id}`);
        setIsActive(true);
        setActiveVersion(fresh.active_version);
        toast(`Published version ${fresh.active_version}`);
      }
    } catch (exc) {
      if (exc instanceof ApiError) {
        toast(exc.message, "error");
        if (exc.issues.length) {
          setConsoleOpen(true);
          setConsoleTab("problems");
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const renameWorkflow = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setName(initial.name);
      return;
    }
    if (trimmed === initial.name) return;
    await save().catch(() => undefined);
    const result = await api<Workflow>(`/api/workflows/${initial.id}`, { method: "PUT", body: { name: trimmed, revision: revision.current } });
    revision.current = result.revision;
    initial.name = trimmed;
  };

  const onSelectionChange = useCallback((params: OnSelectionChangeParams) => {
    setSelection(params.nodes.map((n) => n.id));
    if (params.nodes.length) setPanel("node");
  }, []);

  const selectNode = (id: string) => {
    setNodes((all) => all.map((n) => ({ ...n, selected: n.id === id })));
    flow.fitView({ nodes: [{ id }], duration: 200, maxZoom: 1, padding: 1.2 });
  };

  const selected = selection.length === 1 ? nodes.find((n) => n.id === selection[0]) : null;
  const errorCount = validation?.errors.length || 0;
  const warningCount = validation?.warnings.length || 0;
  const showRight = aiOpen ? panel === "ai" || !selected : false;

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex h-[52px] shrink-0 items-center gap-2 border-b border-line bg-side px-2.5">
        <Tip text="All workflows">
          <Link to="/workflows" aria-label="Back to workflows" className="flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-raised hover:text-ink">
            <ArrowLeft size={16} />
          </Link>
        </Tip>
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="hidden max-w-[120px] truncate text-xs text-faint xl:inline">{workspaceName}</span>
          <span className="hidden text-faint xl:inline">/</span>
          <input
            aria-label="Workflow name"
            className="w-44 min-w-0 rounded border border-transparent bg-transparent px-1.5 py-1 text-sm font-semibold hover:border-line focus:border-primary focus:outline-none xl:w-56"
            value={name}
            disabled={!canEdit}
            maxLength={160}
            onChange={(e) => setName(e.target.value)}
            onBlur={renameWorkflow}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        </div>
        <SaveIndicator state={saveState} />
        {initial.is_demo && <DemoBadge label="Demo workflow" />}
        {isActive && <Badge tone="success">Active{activeVersion ? ` · v${activeVersion}` : ""}</Badge>}

        <div className="ml-auto flex items-center gap-1.5">
          <Tip text="Undo (Ctrl+Z)">
            <Button size="icon" variant="ghost" aria-label="Undo" disabled={!past.current.length || !canEdit} icon={<Undo2 size={15} />} onClick={undo} />
          </Tip>
          <Tip text="Redo (Ctrl+Y)">
            <Button size="icon" variant="ghost" aria-label="Redo" disabled={!future.current.length || !canEdit} icon={<Redo2 size={15} />} onClick={redo} />
          </Tip>
          <ZoomControls />
          <Tip text="Auto layout">
            <Button size="icon" variant="ghost" aria-label="Auto layout" disabled={!canEdit || !nodes.length} icon={<LayoutGrid size={15} />} onClick={autoLayout} />
          </Tip>
          <Tip text="Version history">
            <Button size="icon" variant="ghost" aria-label="Version history" icon={<History size={15} />} onClick={() => setVersionsOpen(true)} />
          </Tip>
          <div className="mx-0.5 h-5 w-px bg-line" />
          <Button
            variant={aiOpen && showRight ? "primary" : "secondary"}
            icon={<Sparkles size={14} />}
            onClick={() => {
              if (showRight) setAiOpen(false);
              else {
                setAiOpen(true);
                setPanel("ai");
              }
            }}
          >
            AI
          </Button>
          <Tip text="Run with every external action simulated">
            <Button disabled={!canEdit} loading={busy === "test"} icon={<FlaskConical size={14} />} onClick={() => run("test")}>
              Test
            </Button>
          </Tip>
          <Button disabled={!canEdit} loading={busy === "publish"} icon={<Power size={14} />} onClick={togglePublish} variant={isActive ? "success" : "secondary"}>
            {isActive ? "Deactivate" : "Publish"}
          </Button>
          <Button variant="primary" disabled={!canEdit} loading={busy === "run"} icon={<Play size={14} />} onClick={() => run("run")}>
            Run
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* library */}
        <div className="w-[208px] shrink-0 border-r border-line bg-side">
          <NodeLibrary specs={specs} onAdd={(s) => addNode(s)} disabled={!canEdit} />
        </div>

        {/* canvas + console */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
            <ReactFlow
              nodes={displayNodes as RFNode[]}
              edges={displayEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              onConnectEnd={() => setHint(null)}
              onSelectionChange={onSelectionChange}
              onNodeDragStart={() => record()}
              onBeforeDelete={async () => {
                record();
                return true;
              }}
              nodesDraggable={canEdit}
              nodesConnectable={canEdit}
              deleteKeyCode={canEdit ? ["Delete", "Backspace"] : null}
              multiSelectionKeyCode={["Control", "Meta"]}
              selectionKeyCode="Shift"
              fitView
              fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
              minZoom={0.2}
              maxZoom={2}
              snapToGrid
              snapGrid={[10, 10]}
              defaultEdgeOptions={{ type: "default" }}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} size={1.3} color="#233149" />
              <MiniMap position="top-right" bgColor="#0C1422" pannable zoomable nodeColor={(n) => CATEGORY[(n.data as FlowNodeData).spec?.category || "data"].dot} maskColor="rgba(8,13,24,.7)" style={{ width: 150, height: 96 }} />
            </ReactFlow>
            {hint && <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-md border border-warning/40 bg-[#0e1726] px-3 py-1.5 text-xs text-[#FCD34D] shadow-panel">{hint}</div>}
            {nodes.length === 0 && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <div className="pointer-events-auto">
                  <EmptyState icon={<Layers size={30} />} title="Start with a trigger" action={canEdit && byType["trigger.manual"] ? <Button variant="primary" icon={<Plus size={14} />} onClick={() => addNode(byType["trigger.manual"], { x: 120, y: 200 })}>Add Manual Trigger</Button> : undefined}>
                    Drag a node from the library, or describe what you want with the AI assistant.
                  </EmptyState>
                </div>
              </div>
            )}
          </div>

          {/* console */}
          <div className={cx("shrink-0 border-t border-line bg-side", consoleOpen ? "h-[244px]" : "h-[34px]")}>
            <div className="flex h-[34px] items-center gap-3 px-3 text-xs">
              <button aria-label={consoleOpen ? "Collapse console" : "Expand console"} className="flex items-center gap-1 font-medium text-muted hover:text-ink" onClick={() => setConsoleOpen(!consoleOpen)}>
                {consoleOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                Console
              </button>
              <button
                className={cx("flex items-center gap-1", errorCount ? "text-[#FBBF24]" : "text-muted")}
                onClick={() => {
                  setConsoleOpen(true);
                  setConsoleTab("problems");
                }}
                data-testid="problem-count"
              >
                {errorCount ? <AlertTriangle size={13} /> : <CircleCheck size={13} className="text-success" />}
                {errorCount ? `${errorCount} problem${errorCount > 1 ? "s" : ""}` : "Valid"}
                {warningCount > 0 && <span className="text-faint"> · {warningCount} warning{warningCount > 1 ? "s" : ""}</span>}
              </button>
              {execution && (
                <div className="flex items-center gap-2">
                  <StatusBadge status={execution.status} />
                  {execution.mode === "test" && <SimulatedBadge />}
                  <span className="tabular text-muted">{duration(execution.duration_ms)}</span>
                  {TERMINAL.includes(execution.status) ? (
                    <Link className="text-primary-hover hover:underline" to={`/executions/${execution.id}`}>
                      Open inspector
                    </Link>
                  ) : (
                    <Button size="sm" icon={<Square size={11} />} onClick={() => api(`/api/executions/${execution.id}/cancel`, { method: "POST" }).catch((e) => toast(e.message, "error"))}>
                      Cancel
                    </Button>
                  )}
                  <button className="text-faint hover:text-ink" onClick={() => { setExecution(null); watching.current = null; }}>
                    Clear
                  </button>
                </div>
              )}
            </div>
            {consoleOpen && (
              <div className="flex h-[210px] flex-col border-t border-line">
                <Tabs
                  value={consoleTab}
                  onChange={setConsoleTab}
                  tabs={[
                    { id: "run", label: "Last run" },
                    { id: "problems", label: `Problems (${errorCount + warningCount})` },
                  ]}
                />
                <div className="min-h-0 flex-1 overflow-y-auto" data-testid="console-body">
                  {consoleTab === "run" &&
                    (execution ? (
                      <div>
                        {execution.error && <div className="border-b border-line bg-danger-soft px-3 py-1.5 text-xs text-[#FCA5A5]">{execution.error}</div>}
                        {execution.nodes.map((row) => (
                          <NodeRunRow key={row.id} run={row} compact onSelect={() => selectNode(row.node_id)} />
                        ))}
                      </div>
                    ) : (
                      <div className="p-4 text-center text-xs text-faint">Press Test or Run to see each node's result here.</div>
                    ))}
                  {consoleTab === "problems" && (
                    <div>
                      {errorCount + warningCount === 0 && <div className="p-4 text-center text-xs text-faint">No problems found.</div>}
                      {[...(validation?.errors || []).map((i) => ({ ...i, level: "error" })), ...(validation?.warnings || []).map((i) => ({ ...i, level: "warning" }))].map((issue, i) => (
                        <button key={i} className="flex w-full items-start gap-2 border-b border-line/60 px-3 py-1.5 text-left text-xs hover:bg-raised" onClick={() => issue.node_id && selectNode(issue.node_id)}>
                          <AlertTriangle size={13} className={cx("mt-0.5 shrink-0", issue.level === "error" ? "text-[#F87171]" : "text-[#FBBF24]")} />
                          <span>{issue.message}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* right panel */}
        {(selected || showRight || selection.length > 1) && (
          <div className="w-[340px] shrink-0 border-l border-line bg-side">
            {showRight ? (
              <AIAssistant workflowId={initial.id} canEdit={canEdit} getDefinition={() => toDefinition(nodesRef.current, edgesRef.current)} onApply={applyProposal} onClose={() => setAiOpen(false)} />
            ) : selection.length > 1 ? (
              <div className="p-4">
                <div className="text-sm font-semibold">{selection.length} nodes selected</div>
                <p className="mt-1 text-xs text-muted">Drag to move them together.</p>
                <div className="mt-3 flex gap-2">
                  <Button size="sm" disabled={!canEdit} onClick={() => duplicate(selection)}>
                    Duplicate
                  </Button>
                  <Button size="sm" disabled={!canEdit} onClick={() => removeNodes(selection)}>
                    Delete
                  </Button>
                </div>
              </div>
            ) : selected && selected.data.spec ? (
              <NodePanel
                key={selected.id}
                workflowId={initial.id}
                node={toDefinition([selected], []).nodes[0]}
                spec={selected.data.spec}
                issues={issuesByNode[selected.id] || []}
                canEdit={canEdit}
                beforeTest={save}
                onChange={(patch) => patchNode(selected.id, patch)}
                onDelete={() => removeNodes([selected.id])}
                onDuplicate={() => duplicate([selected.id])}
                onClose={() => setNodes((all) => all.map((n) => ({ ...n, selected: false })))}
              />
            ) : null}
          </div>
        )}
      </div>
      {versionsOpen && <VersionsModal workflowId={initial.id} canEdit={canEdit} onClose={() => setVersionsOpen(false)} onRestored={reload} />}
    </div>
  );
}

function ReadOnlyMobile({ workflow }: { workflow: Workflow }) {
  const navigate = useNavigate();
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line bg-side py-2 pl-11 pr-3">
        <button aria-label="Back to workflows" className="text-muted" onClick={() => navigate("/workflows")}>
          <ArrowLeft size={16} />
        </button>
        <span className="truncate text-sm font-semibold">{workflow.name}</span>
      </div>
      <div className="p-3">
        <Notice>The editor needs a larger screen. You can inspect this workflow here.</Notice>
      </div>
      <WorkflowPreview definition={workflow.definition!} showControls className="min-h-0 flex-1" />
    </div>
  );
}

export default function EditorPage() {
  const { id } = useParams();
  const { byType } = useCatalogue();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const narrow = useIsNarrow();

  useEffect(() => {
    setWorkflow(null);
    api<Workflow>(`/api/workflows/${id}`)
      .then(setWorkflow)
      .catch((e) => setError(e.message));
  }, [id, nonce]);

  if (error) return <ErrorState message={error} />;
  if (!workflow || !Object.keys(byType).length) {
    return (
      <div className="flex h-full flex-col" aria-label="Loading workflow">
        <div className="h-[52px] border-b border-line bg-side" />
        <div className="flex flex-1 items-center justify-center bg-canvas">
          <Skeleton className="h-20 w-60" />
        </div>
      </div>
    );
  }
  if (narrow) return <ReadOnlyMobile workflow={workflow} />;
  return (
    <ReactFlowProvider key={`${workflow.id}-${nonce}`}>
      <EditorInner workflow={workflow} reload={() => setNonce((n) => n + 1)} />
    </ReactFlowProvider>
  );
}
