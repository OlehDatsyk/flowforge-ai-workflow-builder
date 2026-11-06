import { useState } from "react";
import { BarList, ChartCard, DurationChart, ExecutionVolumeChart, Legend, STATUS_COLORS, StatTile } from "../components/charts";
import { PageBody } from "../components/Layout";
import { ErrorState, PageHeader, SegmentedControl } from "../components/ui";
import { duration, ERROR_TYPE_LABEL, number } from "../lib/format";
import { useApi } from "../lib/hooks";
import { DemoScopeNotice } from "./Overview";

export default function Analytics() {
  const [range, setRange] = useState<"24h" | "7d" | "30d">("30d");
  const [workflowId, setWorkflowId] = useState("");
  const [includeDemo, setIncludeDemo] = useState(true);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const workflows = useApi<any>("/api/workflows", { page_size: 100, sort: "name" });
  const { data, error, loading, reload } = useApi<any>("/api/analytics/overview", {
    range,
    workflow_id: workflowId,
    include_demo: includeDemo,
    start: start ? new Date(start).toISOString() : undefined,
    end: end ? new Date(`${end}T23:59:59`).toISOString() : undefined,
  });
  const t = data?.totals;
  const initial = loading && !data;
  return (
    <PageBody>
      <PageHeader title="Analytics" description="Computed from execution records in the database. Test runs are excluded." />
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <SegmentedControl
          label="Time range"
          value={range}
          onChange={(v) => {
            setRange(v);
            setStart("");
            setEnd("");
          }}
          options={[
            { value: "24h", label: "24 hours" },
            { value: "7d", label: "7 days" },
            { value: "30d", label: "30 days" },
          ]}
        />
        <label className="text-2xs text-muted">
          <span className="sr-only">From date</span>
          <input aria-label="From date" type="date" className="field w-auto" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="text-2xs text-muted">
          <span className="sr-only">To date</span>
          <input aria-label="To date" type="date" className="field w-auto" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <select aria-label="Filter by workflow" className="field w-auto max-w-[240px]" value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}>
          <option value="">All workflows</option>
          {(workflows.data?.items || []).map((w: any) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <label className="ml-auto flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" className="accent-primary" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} />
          Include demonstration records
        </label>
      </div>
      {error && <ErrorState message={error} retry={() => reload()} />}
      {data && data.demo_count > 0 && (
        <div className="mb-3">
          <DemoScopeNotice demo={data.demo_count} real={data.real_count} />
        </div>
      )}
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="Executions" value={number(t?.executions)} loading={initial} />
        <StatTile label="Success rate" value={t?.success_rate != null ? `${t.success_rate}%` : "-"} loading={initial} />
        <StatTile label="Failure rate" value={t?.failure_rate != null ? `${t.failure_rate}%` : "-"} loading={initial} />
        <StatTile label="Average duration" value={duration(t?.avg_duration_ms)} loading={initial} />
        <StatTile label="95th percentile" value={duration(t?.p95_duration_ms)} loading={initial} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <ChartCard
          title="Execution volume"
          loading={initial}
          empty={!!data && !t?.executions}
          legend={<Legend items={[{ label: "Completed", color: STATUS_COLORS.completed }, { label: "Failed", color: STATUS_COLORS.failed }, { label: "Cancelled", color: STATUS_COLORS.cancelled }]} />}
          table={{ headers: ["Period", "Completed", "Failed", "Cancelled"], rows: (data?.series || []).map((p: any) => [new Date(p.bucket).toLocaleString(), p.completed, p.failed, p.cancelled]) }}
        >
          <ExecutionVolumeChart series={data?.series || []} unit={data?.unit} />
        </ChartCard>
        <ChartCard
          title="Average duration"
          loading={initial}
          empty={!!data && t?.avg_duration_ms == null}
          table={{ headers: ["Period", "Average"], rows: (data?.series || []).filter((p: any) => p.avg_duration_ms != null).map((p: any) => [new Date(p.bucket).toLocaleString(), duration(p.avg_duration_ms)]) }}
        >
          <DurationChart series={data?.series || []} unit={data?.unit} />
        </ChartCard>
        <ChartCard title="Workflow usage" height="h-[250px]" loading={initial} empty={!!data && !data.top_workflows.length}>
          <div className="h-full overflow-y-auto pr-1">
            <BarList rows={(data?.top_workflows || []).map((w: any) => ({ label: w.name, value: w.runs, detail: w.avg_duration_ms != null ? `avg ${duration(w.avg_duration_ms)}` : undefined }))} />
          </div>
        </ChartCard>
        <ChartCard title="Most common failure types" height="h-[250px]" loading={initial} empty={!!data && !data.failure_types.length}>
          <div className="h-full overflow-y-auto pr-1">
            <BarList rows={(data?.failure_types || []).map((f: any) => ({ label: ERROR_TYPE_LABEL[f.type] || f.type, value: f.count }))} />
          </div>
        </ChartCard>
        <ChartCard title="AI node usage" height="h-auto" loading={initial} empty={!!data && !data.ai_usage.length}>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line">
                {["Provider", "Calls", "Input tokens", "Output tokens"].map((h) => (
                  <th key={h} className="th">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.ai_usage || []).map((row: any) => (
                <tr key={row.provider} className="border-b border-line/50 last:border-0">
                  <td className="td">{row.provider === "demo" ? "Demo mode (no model called)" : row.provider}</td>
                  <td className="td tabular">{number(row.calls)}</td>
                  <td className="td tabular">{number(row.input_tokens)}</td>
                  <td className="td tabular">{number(row.output_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ChartCard>
        <ChartCard title="Activity by category" height="h-auto" loading={initial} empty={!!data && !data.categories.length}>
          <BarList rows={(data?.categories || []).map((c: any) => ({ label: c.category, value: c.runs }))} />
        </ChartCard>
      </div>
    </PageBody>
  );
}
