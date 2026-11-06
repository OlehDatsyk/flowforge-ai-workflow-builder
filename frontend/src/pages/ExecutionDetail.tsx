import { ArrowLeft, Ban, CheckCircle2, ChevronRight, Hourglass, Loader2, MinusCircle, RotateCcw, Square, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge, Button, cx, DemoBadge, ErrorState, JsonView, Notice, SimulatedBadge, Skeleton, StatusBadge, useFeedback } from "../components/ui";
import { WorkflowPreview } from "../editor/WorkflowPreview";
import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime, duration, ERROR_TYPE_LABEL, shortId } from "../lib/format";
import { useApi, useInterval } from "../lib/hooks";
import { ExecutionDetail as Detail, ExecStatus, NodeRun, TERMINAL } from "../lib/types";

function StatusIcon({ status }: { status: ExecStatus }) {
  const size = 14;
  if (status === "completed") return <CheckCircle2 size={size} className="shrink-0 text-success" aria-label="Completed" />;
  if (status === "failed") return <XCircle size={size} className="shrink-0 text-danger" aria-label="Failed" />;
  if (status === "running") return <Loader2 size={size} className="shrink-0 animate-spin text-primary-hover" aria-label="Running" />;
  if (status === "waiting") return <Hourglass size={size} className="shrink-0 text-cyan" aria-label="Waiting" />;
  if (status === "cancelled") return <Ban size={size} className="shrink-0 text-warning" aria-label="Cancelled" />;
  return <MinusCircle size={size} className="shrink-0 text-faint" aria-label="Skipped" />;
}

export function NodeRunRow({ run, compact, selected, onSelect, timeline }: { run: NodeRun; compact?: boolean; selected?: boolean; onSelect?: () => void; timeline?: { left: number; width: number } }) {
  return (
    <button onClick={onSelect} className={cx("flex w-full items-center gap-2.5 border-b border-line/50 px-3 text-left text-xs transition-colors hover:bg-raised/60", compact ? "py-1.5" : "py-2", selected && "bg-primary-soft")} data-testid={`run-${run.node_name}`}>
      <StatusIcon status={run.status} />
      <span className={cx("min-w-0 truncate font-medium", timeline ? "w-44 shrink-0" : "flex-1", run.status === "skipped" && "text-faint")}>
        {run.node_name}
        {run.iteration != null && <span className="ml-1 font-normal text-faint">#{run.iteration + 1}</span>}
      </span>
      {timeline && (
        <span className="relative hidden h-2 flex-1 rounded-sm bg-raised sm:block" aria-hidden>
          {run.status !== "skipped" && <span className={cx("absolute inset-y-0 rounded-sm", run.status === "failed" ? "bg-danger" : run.status === "running" ? "bg-primary" : "bg-success")} style={{ left: `${timeline.left}%`, width: `max(3px, ${timeline.width}%)` }} />}
        </span>
      )}
      {run.simulated && <SimulatedBadge />}
      {run.attempts > 1 && <Badge tone="warning">{run.attempts} attempts</Badge>}
      {!compact && run.error_type && <Badge tone="danger">{ERROR_TYPE_LABEL[run.error_type] || run.error_type}</Badge>}
      <span className="tabular w-16 shrink-0 text-right text-muted">{run.status === "skipped" ? "Skipped" : duration(run.duration_ms)}</span>
      {compact && run.error && <span className="max-w-[40%] truncate text-[#F87171]" title={run.error}>{run.error}</span>}
      {!compact && <ChevronRight size={13} className="shrink-0 text-faint" />}
    </button>
  );
}

function NodeDetail({ run }: { run: NodeRun }) {
  return (
    <div className="space-y-3 p-3" data-testid="node-detail">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{run.node_name}</h3>
        <StatusBadge status={run.status} />
        {run.simulated && <SimulatedBadge />}
        {run.ai_provider && <Badge tone={run.ai_provider === "demo" ? "cyan" : "ai"}>{run.ai_provider === "demo" ? "Demo AI, no model called" : `AI: ${run.ai_provider}`}</Badge>}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-muted">Type</dt>
        <dd className="truncate font-mono text-[11px]">{run.node_type}</dd>
        <dt className="text-muted">Started</dt>
        <dd>{dateTime(run.started_at)}</dd>
        <dt className="text-muted">Finished</dt>
        <dd>{dateTime(run.finished_at)}</dd>
        <dt className="text-muted">Duration</dt>
        <dd>{duration(run.duration_ms)}</dd>
        <dt className="text-muted">Attempts</dt>
        <dd>{run.attempts}</dd>
        {run.ai_input_tokens != null && (
          <>
            <dt className="text-muted">Tokens</dt>
            <dd>
              {run.ai_input_tokens} in, {run.ai_output_tokens} out
            </dd>
          </>
        )}
      </dl>
      {run.status === "skipped" && <p className="text-xs text-muted">This node did not run because its branch was not taken, or an earlier step stopped the workflow.</p>}
      {run.error && <Notice tone="warning">{run.error}</Notice>}
      {run.status !== "skipped" && (
        <>
          <div>
            <div className="label">Input</div>
            <JsonView value={run.input} maxHeight="max-h-48" />
          </div>
          <div>
            <div className="label">Output{run.output?.ports?.length ? ` (port: ${run.output.ports.join(", ")})` : ""}</div>
            <JsonView value={run.output?.data} maxHeight="max-h-64" />
          </div>
        </>
      )}
    </div>
  );
}

export default function ExecutionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { canEdit } = useAuth();
  const { toast, confirm } = useFeedback();
  const { data, error, loading, reload } = useApi<Detail>(`/api/executions/${id}`);
  const [selected, setSelected] = useState<string | null>(null);
  const active = data && !TERMINAL.includes(data.status);
  useInterval(() => reload(true), active ? 800 : null);

  useEffect(() => {
    if (data && !selected) {
      const failed = data.nodes.find((n) => n.status === "failed");
      setSelected((failed || data.nodes[0])?.id || null);
    }
  }, [data, selected]);

  if (error) return <ErrorState message={error} />;
  if (loading || !data) {
    return (
      <div className="p-6">
        <Skeleton className="mb-3 h-8 w-72" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  const started = data.nodes.filter((n) => n.started_at).map((n) => new Date(n.started_at!).getTime());
  const t0 = started.length ? Math.min(...started) : 0;
  const ends = data.nodes.filter((n) => n.finished_at).map((n) => new Date(n.finished_at!).getTime());
  const span = Math.max(1, (ends.length ? Math.max(...ends) : t0 + 1) - t0);
  const timeline = (n: NodeRun) => (n.started_at ? { left: ((new Date(n.started_at).getTime() - t0) / span) * 100, width: ((n.duration_ms || 0) / span) * 100 } : { left: 0, width: 0 });
  const selectedRun = data.nodes.find((n) => n.id === selected) || null;

  const retry = async () => {
    try {
      let result;
      try {
        result = await api(`/api/executions/${data.id}/retry`, { method: "POST", body: {} });
      } catch (exc) {
        if (exc instanceof ApiError && exc.code === "confirm_side_effects") {
          const ok = await confirm({ title: "Repeat external actions?", body: exc.message, confirm: "Retry anyway", danger: true });
          if (!ok) return;
          result = await api(`/api/executions/${data.id}/retry`, { method: "POST", body: { confirm_side_effects: true } });
        } else throw exc;
      }
      toast("Retry started", "info");
      setSelected(null);
      navigate(`/executions/${result.execution_id}`);
    } catch (exc) {
      toast((exc as Error).message, "error");
    }
  };

  return (
    <div className="mx-auto max-w-[1500px] p-4 md:p-6">
      <div className="mb-4 flex flex-wrap items-start gap-3">
        <Link to="/executions" aria-label="Back to history" className="mt-0.5 rounded p-1 text-muted hover:bg-raised hover:text-ink">
          <ArrowLeft size={16} />
        </Link>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-lg font-semibold">{data.workflow_name}</h1>
            <StatusBadge status={data.status} />
            {data.is_demo && <DemoBadge />}
            {data.mode === "test" && <Badge tone="cyan">Test run: external actions simulated</Badge>}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted">
            <span className="font-mono" title={data.id}>{shortId(data.id)}</span>
            <span>Version {data.version}</span>
            <span className="capitalize">{data.trigger_type} trigger</span>
            <span>Started {dateTime(data.started_at)}</span>
            <span>Ended {dateTime(data.finished_at)}</span>
            <span>Duration {duration(data.duration_ms)}</span>
            <span>{data.nodes_executed} nodes executed</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => navigate(`/workflows/${data.workflow_id}`)}>Open workflow</Button>
          {data.can_cancel && canEdit && (
            <Button icon={<Square size={13} />} onClick={() => api(`/api/executions/${data.id}/cancel`, { method: "POST" }).then(() => reload(true)).catch((e) => toast(e.message, "error"))}>
              Cancel
            </Button>
          )}
          {data.can_retry && canEdit && (
            <Button variant="primary" icon={<RotateCcw size={13} />} onClick={retry}>
              Retry
            </Button>
          )}
        </div>
      </div>
      {data.is_demo && (
        <div className="mb-3">
          <Notice tone="demo">This is a generated demonstration record, not a real execution. Run the workflow to create a real one.</Notice>
        </div>
      )}
      {data.error && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-[#FCA5A5]" role="alert" data-testid="execution-error">
          <XCircle size={15} className="shrink-0" />
          <span className="min-w-0 flex-1 break-words">{data.error}</span>
          {data.error_type && <Badge tone="danger">{ERROR_TYPE_LABEL[data.error_type] || data.error_type}</Badge>}
        </div>
      )}
      {(data.retry_of_id || data.retry_ids.length > 0) && (
        <div className="mb-3 flex flex-wrap gap-3 text-xs text-muted">
          {data.retry_of_id && (
            <span>
              Retry of{" "}
              <Link className="text-primary-hover hover:underline" to={`/executions/${data.retry_of_id}`} onClick={() => setSelected(null)}>
                {shortId(data.retry_of_id)}
              </Link>
            </span>
          )}
          {data.retry_ids.map((rid) => (
            <span key={rid}>
              Retried as{" "}
              <Link className="text-primary-hover hover:underline" to={`/executions/${rid}`} onClick={() => setSelected(null)}>
                {shortId(rid)}
              </Link>
            </span>
          ))}
        </div>
      )}
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-3">
          <section className="card overflow-hidden" aria-label="Execution path">
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2 text-2xs text-muted">
              <span className="text-[13px] font-semibold text-ink">Execution path</span>
              <span className="flex items-center gap-1"><CheckCircle2 size={12} className="text-success" /> Succeeded</span>
              <span className="flex items-center gap-1"><XCircle size={12} className="text-danger" /> Failed</span>
              <span className="flex items-center gap-1"><MinusCircle size={12} className="text-faint" /> Skipped</span>
            </div>
            <WorkflowPreview
              definition={data.definition}
              runs={data.nodes}
              showControls
              className="h-[340px]"
              selectedNodeId={selectedRun?.node_id}
              onNodeClick={(nodeId) => {
                const match = [...data.nodes].reverse().find((n) => n.node_id === nodeId);
                if (match) setSelected(match.id);
              }}
            />
          </section>
          <section className="card overflow-hidden" aria-label="Node timeline">
            <div className="border-b border-line px-3 py-2 text-[13px] font-semibold">Node timeline</div>
            {data.nodes.length === 0 && <div className="p-4 text-center text-xs text-faint">{active ? "Waiting for the first node..." : "No nodes ran."}</div>}
            {data.nodes.map((run) => (
              <NodeRunRow key={run.id} run={run} timeline={timeline(run)} selected={run.id === selected} onSelect={() => setSelected(run.id)} />
            ))}
          </section>
        </div>
        <aside className="card self-start overflow-hidden" aria-label="Node details">
          {selectedRun ? <NodeDetail run={selectedRun} /> : <div className="p-6 text-center text-xs text-faint">Select a node to inspect it.</div>}
        </aside>
      </div>
    </div>
  );
}
