import { List, Table2 } from "lucide-react";
import { ReactNode, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { duration, number } from "../lib/format";
import { cx, EmptyState, Skeleton } from "./ui";

/** Status colours are reserved for execution state. Each ships with a legend label and a table view. */
export const STATUS_COLORS = { completed: "#22C55E", failed: "#EF4444", cancelled: "#94A3B8" };
const GRID = "#1E2A3C";
const AXIS = "#64748B";
const SURFACE = "#111B2B";

function tick(bucket: string, unit: string) {
  const d = new Date(bucket);
  return unit === "hour" ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-2xs text-muted">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export function ChartCard({ title, legend, table, children, loading, empty, height = "h-[240px]" }: { title: string; legend?: ReactNode; table?: { headers: string[]; rows: (string | number)[][] }; children: ReactNode; loading?: boolean; empty?: boolean; height?: string }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="card p-4" aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-[13px] font-semibold">{title}</h2>
        <div className="mr-auto">{!asTable && legend}</div>
        {table && !empty && (
          <button aria-label={asTable ? "Show chart" : "Show as table"} aria-pressed={asTable} title={asTable ? "Show chart" : "Show as table"} className="rounded p-1 text-faint hover:bg-raised hover:text-ink" onClick={() => setAsTable(!asTable)}>
            {asTable ? <List size={14} /> : <Table2 size={14} />}
          </button>
        )}
      </div>
      {loading ? (
        <Skeleton className={cx("w-full", height)} />
      ) : empty ? (
        <div className={cx("flex items-center justify-center", height)}>
          <EmptyState title="No data for this period">Run a workflow to see it here.</EmptyState>
        </div>
      ) : asTable && table ? (
        <div className={cx("overflow-auto", height)}>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line">
                {table.headers.map((h) => (
                  <th key={h} className="th">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, i) => (
                <tr key={i} className="border-b border-line/50">
                  {row.map((cell, j) => (
                    <td key={j} className="tabular px-3 py-1.5">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={height}>{children}</div>
      )}
    </section>
  );
}

function ChartTooltip({ active, payload, label, unit, format }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-[#0e1726] px-2.5 py-2 text-2xs shadow-panel">
      <div className="mb-1 font-medium text-ink">{new Date(label).toLocaleString(undefined, unit === "hour" ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" } : { weekday: "short", month: "short", day: "numeric" })}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center justify-between gap-5 text-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="tabular font-medium text-ink">{format ? format(p.value) : number(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function ExecutionVolumeChart({ series, unit }: { series: any[]; unit: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: -18 }} barCategoryGap="22%">
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="bucket" tickFormatter={(v) => tick(v, unit)} tick={{ fill: AXIS, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} minTickGap={36} />
        <YAxis allowDecimals={false} tick={{ fill: AXIS, fontSize: 11 }} axisLine={false} tickLine={false} />
        <Tooltip cursor={{ fill: "#ffffff08" }} content={<ChartTooltip unit={unit} />} />
        <Bar isAnimationActive={false} dataKey="completed" name="Completed" stackId="a" fill={STATUS_COLORS.completed} stroke={SURFACE} strokeWidth={1} />
        <Bar isAnimationActive={false} dataKey="failed" name="Failed" stackId="a" fill={STATUS_COLORS.failed} stroke={SURFACE} strokeWidth={1} />
        <Bar isAnimationActive={false} dataKey="cancelled" name="Cancelled" stackId="a" fill={STATUS_COLORS.cancelled} stroke={SURFACE} strokeWidth={1} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function DurationChart({ series, unit }: { series: any[]; unit: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={series} margin={{ top: 6, right: 8, bottom: 0, left: -6 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="bucket" tickFormatter={(v) => tick(v, unit)} tick={{ fill: AXIS, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} minTickGap={36} />
        <YAxis tickFormatter={(v) => duration(v)} tick={{ fill: AXIS, fontSize: 11 }} axisLine={false} tickLine={false} width={58} />
        <Tooltip cursor={{ stroke: "#475569" }} content={<ChartTooltip unit={unit} format={duration} />} />
        <Line isAnimationActive={false} dataKey="avg_duration_ms" name="Average duration" stroke="#6366F1" strokeWidth={2} dot={false} connectNulls activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Single-series magnitude: labelled horizontal bars, so identity never depends on colour. */
export function BarList({ rows, format = number, onSelect }: { rows: { label: string; value: number; detail?: string; id?: string }[]; format?: (value: number) => string; onSelect?: (id: string) => void }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-1">
      {rows.map((row) => (
        <button
          key={row.label}
          disabled={!onSelect}
          title={`${row.label}: ${format(row.value)}${row.detail ? ` (${row.detail})` : ""}`}
          onClick={() => row.id && onSelect?.(row.id)}
          className={cx("group block w-full rounded px-1.5 py-1 text-left transition-colors", onSelect && "hover:bg-raised")}
        >
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="truncate text-ink">{row.label}</span>
            <span className="tabular shrink-0 text-muted">
              {format(row.value)}
              {row.detail && <span className="ml-1.5 text-faint">{row.detail}</span>}
            </span>
          </div>
          <div className="h-1.5 rounded-sm bg-raised">
            <div className="h-full rounded-sm bg-primary" style={{ width: `${(row.value / max) * 100}%` }} />
          </div>
        </button>
      ))}
    </div>
  );
}

export function StatTile({ label, value, sub, loading, tone }: { label: string; value: ReactNode; sub?: ReactNode; loading?: boolean; tone?: "danger" }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      {loading ? <Skeleton className="mt-1.5 h-7 w-16" /> : <div className={cx("tabular mt-0.5 text-[22px] font-semibold tracking-tight", tone === "danger" && value !== 0 && "text-[#F87171]")}>{value}</div>}
      {sub && <div className="mt-0.5 truncate text-2xs text-faint">{sub}</div>}
    </div>
  );
}
