import { useNavigate } from "react-router-dom";
import { StatTile, BarList, ChartCard } from "../components/charts";
import { ExecutionTable } from "../components/ExecutionTable";
import { PageBody } from "../components/Layout";
import { PageHeader } from "../components/ui";
import { duration, number } from "../lib/format";
import { useApi } from "../lib/hooks";
import { DemoScopeNotice } from "./Overview";

export default function Executions() {
  const navigate = useNavigate();
  const { data, loading } = useApi<any>("/api/analytics/overview", { range: "30d" });
  const t = data?.totals;
  return (
    <PageBody>
      <PageHeader title="Execution History" description="Every workflow run, with node-level inputs, outputs and errors. Tick two rows to compare them." />
      {data && data.demo_count > 0 && (
        <div className="mb-3">
          <DemoScopeNotice demo={data.demo_count} real={data.real_count} />
        </div>
      )}
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Total executions" value={number(t?.executions)} sub="Last 30 days, no test runs" loading={loading} />
        <StatTile label="Successful" value={number(t?.completed)} loading={loading} />
        <StatTile label="Failed" value={t?.failed ?? "-"} tone="danger" loading={loading} />
        <StatTile label="Average duration" value={duration(t?.avg_duration_ms)} loading={loading} />
      </div>
      <div className="mb-3">
        <ExecutionTable compare pageSize={15} />
      </div>
      <ChartCard title="Most frequently executed workflows" height="h-auto" loading={loading} empty={!!data && !data.top_workflows.length}>
        <BarList onSelect={(id) => navigate(`/workflows/${id}`)} rows={(data?.top_workflows || []).map((w: any) => ({ id: w.workflow_id, label: w.name, value: w.runs, detail: w.failed ? `${w.failed} failed` : undefined }))} />
      </ChartCard>
    </PageBody>
  );
}
