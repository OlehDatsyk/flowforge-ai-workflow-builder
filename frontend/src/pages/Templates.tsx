import { CheckCircle2, LayoutTemplate, Search, Settings2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageBody } from "../components/Layout";
import { Badge, Button, EmptyState, ErrorState, Modal, PageHeader, Skeleton, useFeedback } from "../components/ui";
import { WorkflowPreview } from "../editor/WorkflowPreview";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi, useDebounced } from "../lib/hooks";

export default function Templates() {
  const navigate = useNavigate();
  const { canEdit } = useAuth();
  const { toast } = useFeedback();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [open, setOpen] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const debounced = useDebounced(search);
  const { data, error, loading, reload } = useApi<any>("/api/templates", { search: debounced, category });

  const use = async (slug: string) => {
    setBusy(true);
    try {
      const wf = await api(`/api/templates/${slug}/use`, { method: "POST", body: {} });
      toast("Workflow created from template");
      navigate(`/workflows/${wf.id}`);
    } catch (exc) {
      toast((exc as Error).message, "error");
      setBusy(false);
    }
  };

  return (
    <PageBody>
      <PageHeader title="Workflow Templates" description="Working starting points built only from supported nodes. Using one creates an inactive copy you can review." />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search size={13} className="absolute left-2 top-2 text-faint" />
          <input aria-label="Search templates" className="field pl-7" placeholder="Search templates" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select aria-label="Filter by category" className="field w-auto" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {(data?.categories || []).map((c: string) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      {error && <ErrorState message={error} retry={() => reload()} />}
      {loading && !data ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-72" />
          ))}
        </div>
      ) : data?.items.length === 0 ? (
        <div className="card">
          <EmptyState icon={<LayoutTemplate size={30} />} title="No templates match your search" />
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data?.items.map((t: any) => (
            <article key={t.slug} className="card flex flex-col overflow-hidden" data-testid="template-card">
              <div className="border-b border-line">
                <WorkflowPreview definition={t.definition} className="h-44" />
              </div>
              <div className="flex flex-1 flex-col p-3.5">
                <div className="flex items-center gap-2">
                  <h2 className="flex-1 truncate text-sm font-semibold">{t.name}</h2>
                  <Badge>{t.category}</Badge>
                </div>
                <p className="mt-1.5 flex-1 text-xs text-muted">{t.description}</p>
                <div className="mt-2.5">
                  {t.needs_configuration ? (
                    <Badge tone="warning" icon={<Settings2 size={11} />}>
                      Needs configuration
                    </Badge>
                  ) : (
                    <Badge tone="success" icon={<CheckCircle2 size={11} />}>
                      Works as is
                    </Badge>
                  )}
                </div>
                <div className="mt-3 flex gap-2">
                  <Button variant="primary" size="sm" disabled={!canEdit} loading={busy} onClick={() => use(t.slug)}>
                    Use template
                  </Button>
                  <Button size="sm" onClick={() => setOpen(t)}>
                    Details
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
      {open && (
        <Modal
          title={open.name}
          width="max-w-3xl"
          onClose={() => setOpen(null)}
          footer={
            <>
              <Button onClick={() => setOpen(null)}>Close</Button>
              <Button variant="primary" disabled={!canEdit} loading={busy} onClick={() => use(open.slug)}>
                Use template
              </Button>
            </>
          }
        >
          <div className="overflow-hidden rounded-md border border-line">
            <WorkflowPreview definition={open.definition} showControls className="h-72" />
          </div>
          <div className="mt-4 grid gap-4 text-[13px] sm:grid-cols-2">
            <div>
              <h3 className="label">Expected behaviour</h3>
              <p>{open.expected_behaviour}</p>
            </div>
            <div className="space-y-3">
              <div>
                <h3 className="label">Required integrations</h3>
                <ul className="list-disc space-y-0.5 pl-4">
                  {open.required_integrations.map((r: string) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="label">Configuration requirements</h3>
                {open.configuration_requirements.length === 0 ? (
                  <p className="text-muted">None. It can run straight away.</p>
                ) : (
                  <ul className="list-disc space-y-0.5 pl-4 text-[#FCD34D]">
                    {open.configuration_requirements.map((r: string) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        </Modal>
      )}
    </PageBody>
  );
}
