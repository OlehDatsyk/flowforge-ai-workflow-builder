import { ArrowLeft } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { PageBody } from "../components/Layout";
import { Badge, ErrorState, JsonView, Skeleton, StatusBadge } from "../components/ui";
import { dateTime, duration, shortId } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { ExecutionDetail, NodeRun } from "../lib/types";

const pick = (runs: NodeRun[], id: string) => runs.filter((r) => r.node_id === id).slice(-1)[0];

export default function ExecutionCompare() {
  const [params] = useSearchParams();
  const a = useApi<ExecutionDetail>(`/api/executions/${params.get("a")}`);
  const b = useApi<ExecutionDetail>(`/api/executions/${params.get("b")}`);
  const error = a.error || b.error;
  if (error) return <ErrorState message={error} />;
  if (!a.data || !b.data) {
    return (
      <PageBody>
        <Skeleton className="h-96 w-full" />
      </PageBody>
    );
  }
  const ids: string[] = [];
  for (const run of [...a.data.nodes, ...b.data.nodes]) if (!ids.includes(run.node_id)) ids.push(run.node_id);
  const head = (ex: ExecutionDetail) => (
    <div className="card p-3">
      <div className="flex items-center gap-2">
        <Link to={`/executions/${ex.id}`} className="truncate font-medium text-primary-hover hover:underline">
          {ex.workflow_name}
        </Link>
        <StatusBadge status={ex.status} />
      </div>
      <div className="mt-1 text-2xs text-muted">
        <span className="font-mono">{shortId(ex.id)}</span> · v{ex.version} · {dateTime(ex.started_at)} · {duration(ex.duration_ms)}
      </div>
    </div>
  );
  return (
    <PageBody>
      <div className="mb-4 flex items-center gap-2">
        <Link to="/executions" aria-label="Back to history" className="rounded p-1 text-muted hover:bg-raised hover:text-ink">
          <ArrowLeft size={16} />
        </Link>
        <h1 className="text-lg font-semibold">Compare executions</h1>
      </div>
      <div className="mb-3 grid gap-3 md:grid-cols-2">
        {head(a.data)}
        {head(b.data)}
      </div>
      <div className="space-y-2">
        {ids.map((id) => {
          const left = pick(a.data!.nodes, id);
          const right = pick(b.data!.nodes, id);
          const different = JSON.stringify(left?.output?.data) !== JSON.stringify(right?.output?.data) || left?.status !== right?.status;
          return (
            <details key={id} open={different} className="card overflow-hidden" data-testid="compare-row">
              <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px]">
                <span className="flex-1 truncate font-medium">{left?.node_name || right?.node_name}</span>
                {different ? <Badge tone="warning">Different</Badge> : <Badge>Same</Badge>}
              </summary>
              <div className="grid gap-3 border-t border-line p-3 md:grid-cols-2">
                {[left, right].map((run, i) => (
                  <div key={i} className="min-w-0 space-y-1.5">
                    {run ? (
                      <>
                        <div className="flex items-center gap-2">
                          <StatusBadge status={run.status} />
                          <span className="tabular text-2xs text-muted">{duration(run.duration_ms)}</span>
                        </div>
                        {run.error && <p className="text-xs text-[#F87171]">{run.error}</p>}
                        <JsonView value={run.output?.data} maxHeight="max-h-52" />
                      </>
                    ) : (
                      <p className="text-xs text-faint">This node is not in this execution.</p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </PageBody>
  );
}
