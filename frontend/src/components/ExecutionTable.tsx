import { ArrowDown, ArrowUp, ChevronsUpDown, Eye, GitCompare, Search } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { dateTime, duration, shortId } from "../lib/format";
import { useApi, useDebounced, useInterval } from "../lib/hooks";
import type { ExecutionSummary } from "../lib/types";
import { Button, cx, DemoBadge, EmptyState, ErrorState, Pagination, StatusBadge, TableSkeleton, Tip, Badge } from "./ui";

const COLUMNS: { key: string; label: string; sortable: boolean; className?: string }[] = [
  { key: "id", label: "Execution", sortable: true },
  { key: "workflow_name", label: "Workflow", sortable: true },
  { key: "created_at", label: "Started", sortable: true },
  { key: "duration_ms", label: "Duration", sortable: true },
  { key: "status", label: "Status", sortable: true },
  { key: "nodes_executed", label: "Nodes", sortable: true },
];

export function ExecutionTable({ pageSize = 10, workflowId, initialStatus = "", compare = false, title }: { pageSize?: number; workflowId?: string; initialStatus?: string; compare?: boolean; title?: string }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const status = params.get("status") ?? initialStatus;
  const [sort, setSort] = useState({ key: "created_at", order: "desc" as "asc" | "desc" });
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<string[]>([]);
  const debounced = useDebounced(search);
  const { data, error, loading, reload } = useApi<{ items: ExecutionSummary[]; total: number }>("/api/executions", {
    search: debounced,
    status,
    workflow_id: workflowId,
    sort: sort.key,
    order: sort.order,
    page,
    page_size: pageSize,
  });
  const hasActive = data?.items.some((e) => ["pending", "running", "waiting"].includes(e.status));
  useInterval(() => reload(true), hasActive ? 2000 : null);

  const setStatus = (next: string) => {
    setPage(1);
    const copy = new URLSearchParams(params);
    if (next) copy.set("status", next);
    else copy.delete("status");
    setParams(copy, { replace: true });
  };

  return (
    <section className="card overflow-hidden" aria-label={title || "Executions"}>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-2.5">
        {title && <h2 className="mr-2 text-[13px] font-semibold">{title}</h2>}
        <div className="relative min-w-[180px] flex-1 sm:max-w-xs">
          <Search size={13} className="absolute left-2 top-2 text-faint" />
          <input
            aria-label="Search executions"
            className="field pl-7"
            placeholder="Search by workflow or ID"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <select aria-label="Filter by status" className="field w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {["completed", "failed", "running", "waiting", "pending", "cancelled"].map((s) => (
            <option key={s} value={s}>
              {s[0].toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
        {compare && (
          <Button className="ml-auto" size="sm" disabled={picked.length !== 2} icon={<GitCompare size={13} />} onClick={() => navigate(`/executions/compare?a=${picked[0]}&b=${picked[1]}`)}>
            Compare {picked.length ? `(${picked.length}/2)` : ""}
          </Button>
        )}
      </div>
      {error && <ErrorState message={error} retry={() => reload()} />}
      {loading && !data ? (
        <TableSkeleton rows={pageSize > 8 ? 8 : pageSize} />
      ) : data && data.items.length === 0 ? (
        <EmptyState title={search || status ? "No executions match your filters" : "No executions yet"}>{search || status ? "Try a different search or status." : "Run a workflow and its history appears here."}</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line">
                {compare && <th className="th w-8" aria-label="Select to compare" />}
                {COLUMNS.map((column) => {
                  const active = sort.key === column.key;
                  return (
                    <th key={column.key} className="th" aria-sort={active ? (sort.order === "asc" ? "ascending" : "descending") : "none"}>
                      <button
                        className={cx("inline-flex items-center gap-1 uppercase hover:text-ink", active && "text-ink")}
                        onClick={() => {
                          setPage(1);
                          setSort({ key: column.key, order: active && sort.order === "desc" ? "asc" : "desc" });
                        }}
                      >
                        {column.label}
                        {active ? sort.order === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} /> : <ChevronsUpDown size={11} className="opacity-50" />}
                      </button>
                    </th>
                  );
                })}
                <th className="th text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((ex) => (
                <tr key={ex.id} className="cursor-pointer border-b border-line/50 transition-colors last:border-0 hover:bg-raised/60" onClick={() => navigate(`/executions/${ex.id}`)}>
                  {compare && (
                    <td className="td" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${ex.id} to compare`}
                        className="accent-primary"
                        checked={picked.includes(ex.id)}
                        disabled={!picked.includes(ex.id) && picked.length >= 2}
                        onChange={(e) => setPicked(e.target.checked ? [...picked, ex.id] : picked.filter((id) => id !== ex.id))}
                      />
                    </td>
                  )}
                  <td className="td whitespace-nowrap font-mono text-xs text-muted" title={ex.id}>
                    {shortId(ex.id)}
                  </td>
                  <td className="td max-w-[280px]">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-medium">{ex.workflow_name}</span>
                      {ex.is_demo && <DemoBadge label="Demo" />}
                      {ex.mode === "test" && <Badge tone="cyan">Test</Badge>}
                    </div>
                  </td>
                  <td className="td tabular whitespace-nowrap text-muted">{dateTime(ex.started_at || ex.created_at)}</td>
                  <td className="td tabular whitespace-nowrap text-muted">{duration(ex.duration_ms)}</td>
                  <td className="td">
                    <StatusBadge status={ex.status} />
                  </td>
                  <td className="td tabular text-muted">{ex.nodes_executed}</td>
                  <td className="td text-right">
                    <Tip text="Open execution details" side="top">
                      <Button size="sm" variant="ghost" aria-label={`Open ${ex.id}`} icon={<Eye size={14} />} onClick={() => navigate(`/executions/${ex.id}`)} />
                    </Tip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > 0 && <Pagination page={page} pageSize={pageSize} total={data.total} onChange={setPage} />}
    </section>
  );
}
