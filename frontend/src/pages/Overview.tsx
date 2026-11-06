import { AlertTriangle, LayoutTemplate, Plus, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BarList, ChartCard, DurationChart, ExecutionVolumeChart, Legend, STATUS_COLORS, StatTile } from "../components/charts";
import { ExecutionTable } from "../components/ExecutionTable";
import { PageBody } from "../components/Layout";
import { Button, ErrorState, Notice, PageHeader, SegmentedControl, useFeedback } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { duration, number } from "../lib/format";
import { useApi } from "../lib/hooks";

export function DemoScopeNotice({ demo, real }: { demo: number; real: number }) {
  if (!demo) return null;
  return (
    <Notice tone="demo">
      These figures include <b>{number(demo)} generated demonstration records</b> and {number(real)} real execution{real === 1 ? "" : "s"}.
    </Notice>
  );
}

export default function Overview() {
  const navigate = useNavigate();
  const { canEdit } = useAuth();
  const { toast } = useFeedback();
  const [range, setRange] = useState<"24h" | "7d" | "30d">("7d");
  const { data, error, loading, reload } = useApi<any>("/api/analytics/overview", { range });
  const t = data?.totals;
  const createWorkflow = async () => {
    try {
      const wf = await api("/api/workflows", { method: "POST", body: { name: "Untitled workflow" } });
      navigate(`/workflows/${wf.id}`);
    } catch (exc) {
      toast((exc as Error).message, "error");
    }
  };

  return (
    <PageBody>
      <PageHeader
        title="Overview"
        description="How your automations are performing."
        actions={
          <>
            <Button variant="primary" disabled={!canEdit} icon={<Plus size={14} />} onClick={createWorkflow}>
              Create workflow
            </Button>
            <Button icon={<Sparkles size={14} />} onClick={() => navigate("/ai")}>
              Generate with AI
            </Button>
            <Button icon={<LayoutTemplate size={14} />} onClick={() => navigate("/templates")}>
              Browse templates
            </Button>
            <Button icon={<AlertTriangle size={14} />} onClick={() => navigate("/executions?status=failed")}>
              View failed
            </Button>
          </>
        }
      />
      {error && <ErrorState message={error} retry={() => reload()} />}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">{data && <DemoScopeNotice demo={data.demo_count} real={data.real_count} />}</div>
        <SegmentedControl
          label="Time range"
          value={range}
          onChange={setRange}
          options={[
            { value: "24h", label: "Last 24 hours" },
            { value: "7d", label: "Last 7 days" },
            { value: "30d", label: "Last 30 days" },
          ]}
        />
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Total workflows" value={number(t?.workflows)} loading={loading && !data} />
        <StatTile label="Active workflows" value={number(t?.active_workflows)} loading={loading && !data} />
        <StatTile label="Total executions" value={number(t?.executions)} sub="Excludes test runs" loading={loading && !data} />
        <StatTile label="Successful" value={number(t?.completed)} loading={loading && !data} />
        <StatTile label="Failed" value={t?.failed ?? "-"} tone="danger" loading={loading && !data} />
        <StatTile label="Success rate" value={t?.success_rate != null ? `${t.success_rate}%` : "-"} loading={loading && !data} />
      </div>
      <div className="mb-4 grid gap-3 lg:grid-cols-2">
        <ChartCard
          title="Executions over time"
          loading={loading && !data}
          empty={!!data && !t?.executions}
          legend={
            <Legend
              items={[
                { label: "Completed", color: STATUS_COLORS.completed },
                { label: "Failed", color: STATUS_COLORS.failed },
                { label: "Cancelled", color: STATUS_COLORS.cancelled },
              ]}
            />
          }
          table={{ headers: ["Period", "Completed", "Failed", "Cancelled"], rows: (data?.series || []).map((p: any) => [new Date(p.bucket).toLocaleString(), p.completed, p.failed, p.cancelled]) }}
        >
          <ExecutionVolumeChart series={data?.series || []} unit={data?.unit} />
        </ChartCard>
        <ChartCard
          title="Average execution duration"
          loading={loading && !data}
          empty={!!data && t?.avg_duration_ms == null}
          table={{ headers: ["Period", "Average"], rows: (data?.series || []).filter((p: any) => p.avg_duration_ms != null).map((p: any) => [new Date(p.bucket).toLocaleString(), duration(p.avg_duration_ms)]) }}
        >
          <DurationChart series={data?.series || []} unit={data?.unit} />
        </ChartCard>
        <ChartCard title="Most frequently executed workflows" height="h-[220px]" loading={loading && !data} empty={!!data && !data.top_workflows.length}>
          <div className="h-full overflow-y-auto pr-1">
            <BarList onSelect={(id) => navigate(`/workflows/${id}`)} rows={(data?.top_workflows || []).map((w: any) => ({ id: w.workflow_id, label: w.name, value: w.runs, detail: w.failed ? `${w.failed} failed` : undefined }))} />
          </div>
        </ChartCard>
        <ChartCard title="Activity by category" height="h-[220px]" loading={loading && !data} empty={!!data && !data.categories.length}>
          <div className="h-full overflow-y-auto pr-1">
            <BarList rows={(data?.categories || []).map((c: any) => ({ label: c.category, value: c.runs }))} />
          </div>
        </ChartCard>
      </div>
      <ExecutionTable title="Recent executions" pageSize={8} />
    </PageBody>
  );
}
