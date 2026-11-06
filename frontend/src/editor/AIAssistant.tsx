import { CheckCircle2, FileQuestion, Minus, Plus, Sparkles, Wand2, X } from "lucide-react";
import { useState } from "react";
import { Badge, Button, DemoBadge, Notice, useFeedback } from "../components/ui";
import { ApiError, api } from "../lib/api";
import type { Definition, Proposal } from "../lib/types";

const SUGGESTIONS = ["Add an email notification after the successful execution.", "Add a condition to check whether the amount exceeds £500.", "Add an error-handling branch.", "Simplify this workflow."];

export function ProviderBadge({ provider, model, isDemo }: { provider?: string; model?: string; isDemo?: boolean }) {
  if (isDemo) return <DemoBadge label="Demo planner · no AI model" />;
  if (!provider) return null;
  return (
    <Badge tone="ai" icon={<Sparkles size={11} />}>
      {provider} · {model}
    </Badge>
  );
}

export function ProposalNotes({ proposal }: { proposal: Proposal }) {
  return (
    <div className="space-y-2">
      {proposal.unsupported_requirements.length > 0 && (
        <Notice tone="warning">
          <div className="font-medium">Not supported as requested</div>
          <ul className="mt-0.5 list-disc pl-4 text-xs">
            {proposal.unsupported_requirements.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </Notice>
      )}
      {proposal.required_setup.length > 0 && (
        <Notice>
          <div className="font-medium">Setup you need to do</div>
          <ul className="mt-0.5 list-disc pl-4 text-xs">
            {proposal.required_setup.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </Notice>
      )}
      {proposal.validation.errors.length > 0 && (
        <Notice tone="warning">
          <div className="font-medium">Validation found {proposal.validation.errors.length} problem(s)</div>
          <ul className="mt-0.5 list-disc pl-4 text-xs">
            {proposal.validation.errors.slice(0, 6).map((e, i) => (
              <li key={i}>{e.message}</li>
            ))}
          </ul>
        </Notice>
      )}
      {proposal.notes.map((n, i) => (
        <Notice key={i}>{n}</Notice>
      ))}
    </div>
  );
}

export function AIAssistant({ workflowId, getDefinition, onApply, onClose, canEdit }: { workflowId: string; getDefinition: () => Definition; onApply: (definition: Definition) => void; onClose: () => void; canEdit: boolean }) {
  const { toast } = useFeedback();
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState<"modify" | "explain" | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [explanation, setExplanation] = useState<any>(null);

  const propose = async (text: string) => {
    setBusy("modify");
    setExplanation(null);
    try {
      setProposal(await api<Proposal>("/api/ai/modify", { method: "POST", body: { workflow_id: workflowId, instruction: text, definition: getDefinition() } }));
    } catch (exc) {
      toast(exc instanceof ApiError ? exc.message : "AI request failed", "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2.5">
        <Sparkles size={15} className="text-ai" />
        <span className="flex-1 text-sm font-semibold">AI assistant</span>
        <button aria-label="Close AI assistant" className="rounded p-1 text-muted hover:bg-raised hover:text-ink" onClick={onClose}>
          <X size={15} />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <p className="text-xs text-muted">Describe a change. You review the proposal before anything is applied.</p>
        <textarea aria-label="Describe a change" className="field min-h-[72px] resize-y" placeholder="Add a condition to check..." value={instruction} maxLength={4000} onChange={(e) => setInstruction(e.target.value)} disabled={!canEdit} />
        <div className="flex gap-1.5">
          <Button variant="primary" size="sm" disabled={!canEdit || instruction.trim().length < 3} loading={busy === "modify"} icon={<Wand2 size={12} />} onClick={() => propose(instruction)}>
            Propose change
          </Button>
          <Button
            size="sm"
            loading={busy === "explain"}
            icon={<FileQuestion size={12} />}
            onClick={async () => {
              setBusy("explain");
              setProposal(null);
              try {
                setExplanation(await api("/api/ai/explain", { method: "POST", body: { workflow_id: workflowId, definition: getDefinition() } }));
              } catch (exc) {
                toast((exc as Error).message, "error");
              } finally {
                setBusy(null);
              }
            }}
          >
            Explain workflow
          </Button>
        </div>
        {!proposal && !explanation && (
          <div className="space-y-1">
            {SUGGESTIONS.map((s) => (
              <button key={s} disabled={!canEdit} onClick={() => { setInstruction(s); propose(s); }} className="block w-full rounded border border-line px-2 py-1.5 text-left text-xs text-muted transition-colors hover:border-lineStrong hover:text-ink disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
        )}
        {explanation && (
          <div className="space-y-2 rounded-md border border-line bg-base/40 p-2.5" data-testid="ai-explanation">
            <ProviderBadge provider={explanation.provider} model={explanation.model} isDemo={explanation.is_demo} />
            <p className="text-[13px]">{explanation.summary}</p>
            <ol className="list-decimal space-y-1 pl-4 text-xs text-muted">
              {explanation.steps.map((s: string, i: number) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
            {explanation.risks.length > 0 && (
              <Notice tone="warning">
                <ul className="list-disc pl-4 text-xs">
                  {explanation.risks.map((r: string, i: number) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </Notice>
            )}
          </div>
        )}
        {proposal && (
          <div className="space-y-2.5 rounded-md border border-line bg-base/40 p-2.5" data-testid="ai-proposal">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-semibold">Proposed change</span>
              <ProviderBadge provider={proposal.provider} model={proposal.model} isDemo={proposal.is_demo} />
            </div>
            {proposal.changes.length > 0 && (
              <ul className="space-y-1 text-xs">
                {proposal.changes.map((c, i) => (
                  <li key={i} className="flex gap-1.5">
                    <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-muted" /> {c}
                  </li>
                ))}
              </ul>
            )}
            {proposal.diff && (
              <div className="space-y-1 text-xs">
                {proposal.diff.added_nodes.map((n) => (
                  <div key={n.id} className="flex items-center gap-1.5 text-[#4ADE80]">
                    <Plus size={12} /> {n.name}
                  </div>
                ))}
                {proposal.diff.removed_nodes.map((n) => (
                  <div key={n.id} className="flex items-center gap-1.5 text-[#F87171]">
                    <Minus size={12} /> {n.name}
                  </div>
                ))}
                {proposal.diff.changed_nodes.map((n) => (
                  <div key={n.id} className="flex items-center gap-1.5 text-[#FBBF24]">
                    <Wand2 size={12} /> Changes {n.name}
                  </div>
                ))}
              </div>
            )}
            <ProposalNotes proposal={proposal} />
            <div className="flex gap-1.5">
              {proposal.status === "ready" && proposal.workflow.definition && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    onApply(proposal.workflow.definition!);
                    setProposal(null);
                    setInstruction("");
                    toast("Change applied to the canvas. Undo with Ctrl+Z.");
                  }}
                >
                  Apply to canvas
                </Button>
              )}
              <Button size="sm" onClick={() => setProposal(null)}>
                {proposal.status === "ready" ? "Discard" : "Dismiss"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
