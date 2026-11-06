import { ArrowRight, Check, Sparkles, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageBody } from "../components/Layout";
import { Badge, Button, Field, Notice, PageHeader, Skeleton, useFeedback } from "../components/ui";
import { CATEGORY, ICONS } from "../editor/FlowNode";
import { ProposalNotes, ProviderBadge } from "../editor/AIAssistant";
import { WorkflowPreview } from "../editor/WorkflowPreview";
import { ApiError, api } from "../lib/api";
import { useAuth, useCatalogue } from "../lib/auth";
import { number, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { DefNode, Definition, Proposal } from "../lib/types";

function AnalysisBlock({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <div className="mb-0.5 text-2xs font-semibold uppercase tracking-wide text-faint">{title}</div>
      <ul className="space-y-0.5 text-xs text-muted">
        {items.map((item, i) => (
          <li key={i} className="flex gap-1.5">
            <Check size={12} className="mt-0.5 shrink-0" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function NodeReview({ node, onChange, onRemove, removable }: { node: DefNode; onChange: (node: DefNode) => void; onRemove: () => void; removable: boolean }) {
  const { byType } = useCatalogue();
  const spec = byType[node.type];
  const Icon = spec && ICONS[spec.icon];
  return (
    <div className="flex items-center gap-2 rounded-md border border-line bg-base/40 px-2 py-1.5">
      <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded ${spec ? CATEGORY[spec.category].tile : "bg-raised"}`}>{Icon && <Icon size={13} />}</span>
      <input aria-label={`Name of ${node.name}`} className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 text-xs font-medium hover:border-line focus:border-primary focus:outline-none" value={node.name} maxLength={160} onChange={(e) => onChange({ ...node, name: e.target.value })} />
      <span className="hidden text-2xs text-faint sm:block">{spec?.label || node.type}</span>
      {removable && <Button size="sm" variant="ghost" aria-label={`Remove ${node.name}`} icon={<Trash2 size={12} />} onClick={onRemove} />}
    </div>
  );
}

export default function AIBuilder() {
  const navigate = useNavigate();
  const { canEdit } = useAuth();
  const { toast } = useFeedback();
  const status = useApi<any>("/api/ai/status");
  const history = useApi<any>("/api/ai/conversations", { page_size: 5 });
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [definition, setDefinition] = useState<Definition | null>(null);
  const [name, setName] = useState("");
  const [validation, setValidation] = useState<Proposal["validation"] | null>(null);

  const load = (result: Proposal) => {
    setProposal(result);
    setDefinition(result.workflow.definition);
    setName(result.workflow.name);
    setValidation(result.validation);
  };

  const generate = async (text: string) => {
    setBusy(true);
    setProposal(null);
    try {
      load(await api<Proposal>("/api/ai/generate", { method: "POST", body: { prompt: text } }));
      history.reload(true);
    } catch (exc) {
      toast(exc instanceof ApiError ? exc.message : "Generation failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const updateDefinition = async (next: Definition) => {
    setDefinition(next);
    try {
      setValidation(await api("/api/definitions/validate", { method: "POST", body: { definition: next, mode: "test" } }));
    } catch {
      /* the save endpoint validates again */
    }
  };

  const removeNode = (id: string) => {
    if (!definition) return;
    const incoming = definition.edges.filter((e) => e.target === id);
    const outgoing = definition.edges.filter((e) => e.source === id);
    // Reconnect around the removed step so a linear plan stays connected.
    const bridged = incoming.flatMap((i) => outgoing.map((o) => ({ id: `e_${i.source}_${o.target}`, source: i.source, source_port: i.source_port, target: o.target, target_port: "main" })));
    updateDefinition({ ...definition, nodes: definition.nodes.filter((n) => n.id !== id), edges: [...definition.edges.filter((e) => e.source !== id && e.target !== id), ...bridged] });
  };

  const accept = async () => {
    if (!proposal || !definition) return;
    setSaving(true);
    try {
      const wf = await api(`/api/ai/conversations/${proposal.conversation_id}/accept`, { method: "POST", body: { name: name.trim() || undefined, definition } });
      toast("Saved as an inactive workflow. Review it before publishing.");
      navigate(`/workflows/${wf.id}`);
    } catch (exc) {
      toast(exc instanceof ApiError ? exc.message : "Could not save", "error");
      setSaving(false);
    }
  };

  const isDemo = status.data?.is_demo;
  return (
    <PageBody>
      <PageHeader title="AI Workflow Builder" description="Describe a task in plain English. You get a proposal built from supported nodes, and nothing is saved or run until you approve it." actions={status.data && <ProviderBadge provider={status.data.provider} model={status.data.model} isDemo={isDemo} />} />
      {isDemo && (
        <div className="mb-4">
          <Notice tone="demo">
            <b>Demonstration mode.</b> No AI provider is configured, so proposals come from a rule-based keyword planner, not an AI model. Connect Claude, OpenAI or Gemini under{" "}
            <button className="underline" onClick={() => navigate("/integrations")}>
              Integrations
            </button>{" "}
            for real generation.
          </Notice>
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <div className="space-y-3">
          <section className="card p-3.5">
            <Field label="What should this workflow do?" htmlFor="ai-prompt">
              <textarea id="ai-prompt" className="field min-h-[120px] resize-y" maxLength={4000} placeholder="When a new order arrives, check whether the total exceeds £500..." value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            </Field>
            <Button className="mt-2.5 w-full" variant="primary" disabled={!canEdit || prompt.trim().length < 5} loading={busy} icon={<Sparkles size={14} />} onClick={() => generate(prompt)}>
              Generate proposal
            </Button>
            <div className="mt-3 space-y-1">
              <div className="text-2xs font-semibold uppercase tracking-wide text-faint">Examples</div>
              {(status.data?.examples || []).map((example: string) => (
                <button key={example} disabled={!canEdit} onClick={() => { setPrompt(example); generate(example); }} className="block w-full rounded border border-line px-2 py-1.5 text-left text-xs text-muted transition-colors hover:border-lineStrong hover:text-ink disabled:opacity-50">
                  {example}
                </button>
              ))}
            </div>
          </section>
          {(history.data?.items || []).length > 0 && (
            <section className="card p-3.5">
              <h2 className="mb-2 text-[13px] font-semibold">Recent proposals</h2>
              <div className="space-y-1">
                {history.data.items.map((item: any) => (
                  <button key={item.id} className="block w-full rounded px-1.5 py-1 text-left hover:bg-raised" onClick={() => (item.workflow_id ? navigate(`/workflows/${item.workflow_id}`) : load({ ...item.proposal, conversation_id: item.id }))}>
                    <div className="truncate text-xs">{item.prompt}</div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-faint">
                      {timeAgo(item.created_at)} · {item.status === "accepted" ? "Saved" : item.status}
                      {item.is_demo && " · demo planner"}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>

        <section className="card min-h-[420px] overflow-hidden" aria-label="Proposal" data-testid="proposal">
          {busy && (
            <div className="space-y-3 p-4" aria-label="Generating">
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-64 w-full" />
            </div>
          )}
          {!busy && !proposal && (
            <div className="flex h-full min-h-[420px] flex-col items-center justify-center p-8 text-center">
              <Sparkles size={28} className="mb-3 text-faint" />
              <div className="text-sm font-semibold">Your proposal appears here</div>
              <p className="mt-1 max-w-sm text-[13px] text-muted">The planner analyses the request, picks supported nodes, and validates the result. You can edit it before saving.</p>
            </div>
          )}
          {!busy && proposal && (
            <div>
              <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
                {definition ? <input aria-label="Workflow name" className="field min-w-[180px] flex-1 font-medium sm:max-w-sm" value={name} maxLength={160} onChange={(e) => setName(e.target.value)} /> : <span className="flex items-center gap-1.5 text-sm font-semibold"><X size={15} className="text-[#F87171]" /> This can't be built with the available nodes</span>}
                <ProviderBadge provider={proposal.provider} model={proposal.model} isDemo={proposal.is_demo} />
                {validation?.valid ? <Badge tone="success">Valid</Badge> : definition && <Badge tone="warning">Needs fixes</Badge>}
                {!proposal.is_demo && proposal.usage?.input_tokens != null && <span className="tabular text-2xs text-faint">{number((proposal.usage.input_tokens || 0) + (proposal.usage.output_tokens || 0))} tokens</span>}
                {definition && (
                  <div className="ml-auto flex gap-2">
                    <Button size="sm" onClick={() => setProposal(null)}>
                      Discard
                    </Button>
                    <Button size="sm" variant="primary" disabled={!canEdit || !definition.nodes.length} loading={saving} icon={<ArrowRight size={13} />} onClick={accept}>
                      Save and open in editor
                    </Button>
                  </div>
                )}
              </div>
              {definition && definition.nodes.length > 0 && <WorkflowPreview key={JSON.stringify(definition.edges) + definition.nodes.length} definition={definition} showControls className="h-[280px] border-b border-line" />}
              <div className="grid gap-4 p-3.5 lg:grid-cols-2">
                <div className="space-y-3">
                  {proposal.analysis?.summary && <p className="text-xs text-muted">{proposal.analysis.summary}</p>}
                  <AnalysisBlock title="Trigger" items={proposal.analysis?.triggers} />
                  <AnalysisBlock title="Processing" items={proposal.analysis?.processing} />
                  <AnalysisBlock title="Conditions" items={proposal.analysis?.conditions} />
                  <AnalysisBlock title="Integrations" items={proposal.analysis?.integrations} />
                </div>
                <div className="space-y-3">
                  <ProposalNotes proposal={{ ...proposal, validation: validation || proposal.validation }} />
                  {definition && (
                    <div>
                      <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-faint">Review steps</div>
                      <div className="space-y-1">
                        {definition.nodes.map((node) => (
                          <NodeReview key={node.id} node={node} removable={definition.nodes.length > 1} onRemove={() => removeNode(node.id)} onChange={(next) => setDefinition({ ...definition, nodes: definition.nodes.map((n) => (n.id === node.id ? next : n)) })} />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </PageBody>
  );
}
