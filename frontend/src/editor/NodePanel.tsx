import { Check, Copy, KeyRound, Link2, Play, RefreshCw, Send, Trash2, Copy as Duplicate, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Field, JsonView, Modal, Notice, SimulatedBadge, StatusBadge, Tabs, Toggle, useFeedback, cx } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { dateTime, duration, pretty } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { DefNode, Issue, NodeSettings, NodeSpec } from "../lib/types";
import { ConfigForm } from "./ConfigForm";
import { CATEGORY, ICONS } from "./FlowNode";
import { DEFAULT_SETTINGS } from "./graph";

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm"
      aria-label="Copy"
      icon={done ? <Check size={12} /> : <Copy size={12} />}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    />
  );
}

function WebhookPanel({ workflowId, nodeId, authMode, canEdit, beforeTest }: { workflowId: string; nodeId: string; authMode: string; canEdit: boolean; beforeTest: () => Promise<void> }) {
  const { data, reload } = useApi<any>(`/api/workflows/${workflowId}/triggers`);
  const { toast } = useFeedback();
  const [secret, setSecret] = useState<string | null>(null);
  const hook = data?.webhooks?.find((h: any) => h.node_id === nodeId);
  const requests = useApi<any[]>(hook ? `/api/webhook-triggers/${hook.id}/requests` : null);
  if (!hook) return <p className="text-xs text-faint">The endpoint appears after this node is saved.</p>;
  return (
    <div className="space-y-3">
      <div>
        <div className="label flex items-center gap-1.5">
          <Link2 size={12} /> Endpoint
          <Badge tone={hook.live ? "success" : "neutral"}>{hook.live ? "Live" : "Not live"}</Badge>
        </div>
        <div className="flex gap-1.5">
          <input readOnly aria-label="Webhook URL" className="field-mono min-w-0 flex-1 text-[11px]" value={hook.url} />
          <CopyButton text={hook.url} />
        </div>
        {!hook.live && <p className="mt-1 text-2xs text-faint">Publish the workflow to start receiving requests.</p>}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted">Accept requests</span>
        <Toggle
          checked={hook.enabled}
          disabled={!canEdit}
          label="Accept requests"
          onChange={async (enabled) => {
            await api(`/api/webhook-triggers/${hook.id}`, { method: "PATCH", body: { enabled } });
            reload(true);
          }}
        />
      </div>
      {authMode !== "none" && (
        <div>
          <div className="label flex items-center gap-1.5">
            <KeyRound size={12} /> {authMode === "hmac" ? "Signing secret" : "Secret token"}
          </div>
          {secret ? (
            <>
              <div className="flex gap-1.5">
                <input readOnly aria-label="Secret" className="field-mono min-w-0 flex-1 text-[11px]" value={secret} />
                <CopyButton text={secret} />
              </div>
              <p className="mt-1 text-2xs text-[#FBBF24]">Copy this now. It will not be shown again.</p>
            </>
          ) : (
            <Button
              size="sm"
              disabled={!canEdit}
              icon={<RefreshCw size={12} />}
              onClick={async () => {
                const result = await api(`/api/webhook-triggers/${hook.id}/rotate-secret`, { method: "POST" });
                setSecret(result.secret);
              }}
            >
              Generate new secret
            </Button>
          )}
          <p className="mt-1.5 text-2xs text-faint">
            {authMode === "hmac" ? "Send X-FlowForge-Timestamp and X-FlowForge-Signature: sha256=HMAC(secret, timestamp + \".\" + body)." : "Send the secret in the X-FlowForge-Token header."}
          </p>
        </div>
      )}
      <Button
        size="sm"
        disabled={!canEdit}
        icon={<Send size={12} />}
        onClick={async () => {
          try {
            await beforeTest();
            const r = await api(`/api/webhook-triggers/${hook.id}/test`, { method: "POST", body: {} });
            toast("Test request sent. Side effects are simulated.", "info");
            requests.reload(true);
            window.dispatchEvent(new CustomEvent("ff-watch-execution", { detail: r.execution_id }));
          } catch (exc) {
            toast((exc as Error).message, "error");
          }
        }}
      >
        Send test request
      </Button>
      <div>
        <div className="label flex items-center justify-between">
          Incoming requests
          <button className="text-2xs text-primary-hover hover:underline" onClick={() => requests.reload(true)}>
            Refresh
          </button>
        </div>
        <div className="max-h-44 overflow-y-auto rounded-md border border-line">
          {(requests.data || []).length === 0 && <div className="px-2.5 py-3 text-center text-2xs text-faint">No requests yet</div>}
          {(requests.data || []).map((r) => (
            <div key={r.id} className="border-b border-line/60 px-2.5 py-1.5 text-2xs last:border-0">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono">
                  <span className={r.status_code < 300 ? "text-[#4ADE80]" : "text-[#F87171]"}>{r.status_code}</span> {r.method}
                </span>
                <span className="text-faint">{dateTime(r.received_at)}</span>
              </div>
              <div className="truncate text-muted" title={r.outcome}>
                {r.outcome}
              </div>
              {r.execution_id && (
                <Link className="text-primary-hover hover:underline" to={`/executions/${r.execution_id}`}>
                  View execution
                </Link>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SchedulePanel({ workflowId, nodeId }: { workflowId: string; nodeId: string }) {
  const { data } = useApi<any>(`/api/workflows/${workflowId}/triggers`);
  const schedule = data?.schedules?.find((s: any) => s.node_id === nodeId);
  if (!schedule) return <p className="text-xs text-faint">Publish the workflow to start the schedule.</p>;
  return (
    <dl className="space-y-1.5 text-xs">
      <div className="flex justify-between">
        <dt className="text-muted">Status</dt>
        <dd>{schedule.enabled ? <Badge tone="success">Scheduled</Badge> : <Badge>Not running. Publish to start.</Badge>}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-muted">Next run</dt>
        <dd>{dateTime(schedule.next_run_at)}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-muted">Last run</dt>
        <dd>{dateTime(schedule.last_run_at)}</dd>
      </div>
    </dl>
  );
}

function SettingsTab({ settings, onChange, spec, config, disabled }: { settings: NodeSettings; onChange: (settings: NodeSettings) => void; spec: NodeSpec; config: Record<string, any>; disabled?: boolean }) {
  const retry = { ...DEFAULT_SETTINGS.retry, ...settings.retry };
  const nonIdempotent = spec.type === "integration.email" || spec.type === "integration.webhook_send" || (spec.type === "integration.http" && !["GET", undefined].includes(config.method)) || (spec.type === "integration.database" && ["insert", "update", "delete", undefined].includes(config.operation));
  return (
    <div className="space-y-3.5">
      <Field label="On error" hint={settings.on_error === "error_branch" ? "Connect the red Error output on the node to handle failures." : undefined}>
        <select aria-label="On error" className="field" disabled={disabled} value={settings.on_error || "stop"} onChange={(e) => onChange({ ...settings, on_error: e.target.value as NodeSettings["on_error"] })}>
          <option value="stop">Stop the workflow (Failed)</option>
          <option value="continue">Continue, passing the error along</option>
          <option value="error_branch">Follow an error branch</option>
        </select>
      </Field>
      <Field label="Timeout (seconds)">
        <input className="field" type="number" min={1} max={300} disabled={disabled} value={settings.timeout_seconds ?? 30} onChange={(e) => onChange({ ...settings, timeout_seconds: Math.max(1, Math.min(300, Number(e.target.value) || 30)) })} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Attempts">
          <input className="field" type="number" min={1} max={5} disabled={disabled} value={retry.max_attempts} onChange={(e) => onChange({ ...settings, retry: { ...retry, max_attempts: Math.max(1, Math.min(5, Number(e.target.value) || 1)) } })} />
        </Field>
        <Field label="Retry delay (ms)">
          <input className="field" type="number" min={0} max={60000} disabled={disabled} value={retry.delay_ms} onChange={(e) => onChange({ ...settings, retry: { ...retry, delay_ms: Math.max(0, Math.min(60000, Number(e.target.value) || 0)) } })} />
        </Field>
      </div>
      {nonIdempotent && (
        <div className="rounded-md border border-warning/30 bg-warning-soft p-2.5">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs font-medium text-[#FCD34D]">Allow retries of this action</span>
            <Toggle checked={retry.allow_non_idempotent} disabled={disabled} label="Allow retries of a non-idempotent action" onChange={(allow_non_idempotent) => onChange({ ...settings, retry: { ...retry, allow_non_idempotent } })} />
          </div>
          <p className="mt-1 text-2xs text-[#FCD34D]/80">This action changes external state, so a retry could repeat it. It is not retried unless you allow it.</p>
        </div>
      )}
    </div>
  );
}

function SchemaBlock({ title, schema }: { title: string; schema: any }) {
  if (!schema || Object.keys(schema).length === 0) return null;
  return (
    <div>
      <div className="label">{title}</div>
      <JsonView value={schema} maxHeight="max-h-40" />
    </div>
  );
}

function TestTab({ workflowId, node, canEdit }: { workflowId: string; node: DefNode; canEdit: boolean }) {
  const { toast, confirm } = useFeedback();
  const { data: last, reload } = useApi<any>(`/api/workflows/${workflowId}/nodes/${node.id}/last-result`);
  const [input, setInput] = useState("{}");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setResult(null);
    setInput("{}");
  }, [node.id]);
  useEffect(() => {
    if (last?.input && input === "{}") setInput(pretty(last.input));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [last]);

  const run = async (live: boolean) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(input || "{}");
    } catch {
      toast("Test input is not valid JSON", "error");
      return;
    }
    if (live && !(await confirm({ title: `Run "${node.name}" for real?`, body: "This performs the real action, such as sending the request, sending the email or writing the record.", confirm: "Run for real", danger: true }))) return;
    setBusy(true);
    try {
      setResult(await api(`/api/workflows/${workflowId}/nodes/${node.id}/test`, { method: "POST", body: { input: parsed, node, allow_side_effects: live } }));
    } catch (exc) {
      toast(exc instanceof ApiError ? exc.message : "Test failed", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3.5">
      <Field label="Test input (available as {{ input }})">
        <textarea aria-label="Test input" className="field-mono min-h-[90px] resize-y" spellCheck={false} value={input} onChange={(e) => setInput(e.target.value)} />
      </Field>
      <Button variant="primary" size="sm" disabled={!canEdit} loading={busy} icon={<Play size={12} />} onClick={() => run(false)}>
        Test this node
      </Button>
      {result && (
        <div className="space-y-2" data-testid="node-test-result">
          <div className="flex items-center gap-2">
            <StatusBadge status={result.status} />
            {result.simulated && <SimulatedBadge />}
            <span className="tabular text-2xs text-muted">{duration(result.duration_ms)}</span>
          </div>
          {result.error && <Notice tone="warning">{result.error}</Notice>}
          {result.outputs && <JsonView value={result.outputs} />}
          {result.simulated && result.outputs && Object.values(result.outputs).some((v: any) => v?.simulated) && canEdit && (
            <Button size="sm" variant="danger" onClick={() => run(true)}>
              Run this action for real...
            </Button>
          )}
        </div>
      )}
      <div className="border-t border-line pt-3">
        <div className="label flex items-center justify-between">
          Last execution result
          <button className="text-2xs text-primary-hover hover:underline" onClick={() => reload(true)}>
            Refresh
          </button>
        </div>
        {!last && <p className="text-xs text-faint">This node has not run yet.</p>}
        {last && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <StatusBadge status={last.status} />
              {last.simulated && <SimulatedBadge />}
              <span className="text-2xs text-muted">{dateTime(last.started_at)}</span>
              <Link className="ml-auto text-2xs text-primary-hover hover:underline" to={`/executions/${last.execution_id}`}>
                Open
              </Link>
            </div>
            {last.error && <Notice tone="warning">{last.error}</Notice>}
            {last.output && <JsonView value={last.output.data} maxHeight="max-h-52" />}
          </div>
        )}
      </div>
    </div>
  );
}

type Tab = "config" | "settings" | "test" | "docs";

export function NodePanel({
  workflowId,
  node,
  spec,
  issues,
  canEdit,
  onChange,
  onDelete,
  onDuplicate,
  onClose,
  beforeTest,
}: {
  workflowId: string;
  node: DefNode;
  spec: NodeSpec;
  issues: Issue[];
  canEdit: boolean;
  onChange: (patch: Partial<DefNode>) => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onClose: () => void;
  beforeTest: () => Promise<void>;
}) {
  const [tab, setTab] = useState<Tab>("config");
  const Icon = ICONS[spec.icon];
  const errors = issues.length;
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line p-3">
        <div className="flex items-start gap-2.5">
          <div className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-md", CATEGORY[spec.category].tile)}>{Icon && <Icon size={16} />}</div>
          <div className="min-w-0 flex-1">
            <input aria-label="Node name" className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-sm font-semibold hover:border-line focus:border-primary focus:outline-none" value={node.name} disabled={!canEdit} maxLength={160} onChange={(e) => onChange({ name: e.target.value })} />
            <div className="px-1 text-2xs text-faint">
              {spec.label} · <span className="font-mono">{spec.type}</span>
            </div>
          </div>
          <button aria-label="Close panel" className="rounded p-1 text-muted hover:bg-raised hover:text-ink" onClick={onClose}>
            <X size={15} />
          </button>
        </div>
        <p className="mt-2 text-xs text-muted">{spec.description}</p>
        <div className="mt-2 flex gap-1.5">
          <Button size="sm" disabled={!canEdit} icon={<Duplicate size={12} />} onClick={onDuplicate}>
            Duplicate
          </Button>
          <Button size="sm" disabled={!canEdit} icon={<Trash2 size={12} />} onClick={onDelete}>
            Delete
          </Button>
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "config", label: errors ? `Configure (${errors})` : "Configure" },
          { id: "settings", label: "Error handling" },
          { id: "test", label: "Test" },
          { id: "docs", label: "Schema" },
        ]}
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "config" && (
          <div className="space-y-4">
            {issues.filter((i) => !i.field).map((i, n) => (
              <Notice key={n} tone="warning">
                {i.message}
              </Notice>
            ))}
            <ConfigForm spec={spec} config={node.config} issues={issues} disabled={!canEdit} onChange={(config) => onChange({ config })} />
            <Field label="Notes">
              <textarea className="field min-h-[52px] resize-y" disabled={!canEdit} maxLength={1000} value={node.description || ""} onChange={(e) => onChange({ description: e.target.value })} />
            </Field>
            {spec.type === "trigger.webhook" && (
              <div className="border-t border-line pt-3">
                <WebhookPanel workflowId={workflowId} nodeId={node.id} authMode={node.config.auth_mode || "hmac"} canEdit={canEdit} beforeTest={beforeTest} />
              </div>
            )}
            {spec.type === "trigger.schedule" && (
              <div className="border-t border-line pt-3">
                <SchedulePanel workflowId={workflowId} nodeId={node.id} />
              </div>
            )}
            <details className="rounded-md border border-line bg-base/40 px-2.5 py-2 text-2xs text-muted">
              <summary className="cursor-pointer font-medium">Expression help</summary>
              <div className="mt-1.5 space-y-1 font-mono text-[10.5px]">
                <div>{"{{ input.field }}"} previous node</div>
                <div>{"{{ trigger.body.field }}"} trigger data</div>
                <div>{'{{ nodes["Node Name"].field }}'} earlier node</div>
                <div>{"{{ vars.name }}"} variable</div>
                <div>{"{{ item }} {{ index }}"} inside loops</div>
                <div>{'{{ input.name | upper | default:"x" }}'} filters</div>
              </div>
            </details>
          </div>
        )}
        {tab === "settings" && <SettingsTab settings={node.settings || DEFAULT_SETTINGS} spec={spec} config={node.config} disabled={!canEdit} onChange={(settings) => onChange({ settings })} />}
        {tab === "test" && <TestTab workflowId={workflowId} node={node} canEdit={canEdit} />}
        {tab === "docs" && (
          <div className="space-y-3">
            <div>
              <div className="label">Input</div>
              <div className="flex flex-wrap gap-1">
                {spec.inputs.length === 0 && <Badge>None (starts the workflow)</Badge>}
                {spec.inputs.map((p) => (
                  <Badge key={p.id}>accepts {p.data_type}</Badge>
                ))}
              </div>
            </div>
            <div>
              <div className="label">Outputs</div>
              <div className="flex flex-wrap gap-1">
                {spec.outputs.map((p) => (
                  <Badge key={p.id}>
                    {p.label || p.id}: {p.data_type}
                  </Badge>
                ))}
              </div>
            </div>
            <SchemaBlock title="Output schema" schema={spec.output_schema} />
          </div>
        )}
      </div>
    </div>
  );
}

export function VersionsModal({ workflowId, onClose, onRestored, canEdit }: { workflowId: string; onClose: () => void; onRestored: () => void; canEdit: boolean }) {
  const { data, reload } = useApi<any[]>(`/api/workflows/${workflowId}/versions`);
  const { toast, confirm } = useFeedback();
  const [note, setNote] = useState("");
  return (
    <Modal title="Version history" onClose={onClose} width="max-w-xl">
      {canEdit && (
        <div className="mb-3 flex gap-2">
          <input aria-label="Version note" className="field" placeholder="Describe this checkpoint" maxLength={240} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button
            variant="primary"
            onClick={async () => {
              await api(`/api/workflows/${workflowId}/versions`, { method: "POST", body: { note } });
              setNote("");
              reload(true);
              toast("Version saved");
            }}
          >
            Save version
          </Button>
        </div>
      )}
      <div className="divide-y divide-line rounded-md border border-line">
        {(data || []).map((v) => (
          <div key={v.id} className="flex items-center gap-3 px-3 py-2">
            <span className="tabular w-8 font-mono text-xs text-muted">v{v.version}</span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px]">{v.note || "No description"}</div>
              <div className="text-2xs text-faint">
                {dateTime(v.created_at)} · {v.node_count} nodes
              </div>
            </div>
            {v.is_active && <Badge tone="success">Published</Badge>}
            {v.is_current && <Badge tone="primary">Current</Badge>}
            {canEdit && !v.is_current && (
              <Button
                size="sm"
                onClick={async () => {
                  if (await confirm({ title: `Restore version ${v.version}?`, body: "Your current draft is kept as a version first, so nothing is lost.", confirm: "Restore" })) {
                    await api(`/api/workflows/${workflowId}/versions/${v.id}/restore`, { method: "POST" });
                    toast(`Restored version ${v.version}`);
                    onRestored();
                    onClose();
                  }
                }}
              >
                Restore
              </Button>
            )}
          </div>
        ))}
      </div>
    </Modal>
  );
}
