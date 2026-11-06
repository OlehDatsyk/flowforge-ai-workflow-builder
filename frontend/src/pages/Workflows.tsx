import { Copy, FolderInput, MoreHorizontal, Pencil, Plus, Search, Sparkles, Trash2, Workflow as WorkflowIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageBody } from "../components/Layout";
import { Badge, Button, cx, DemoBadge, EmptyState, ErrorState, Field, Modal, PageHeader, Pagination, Skeleton, useFeedback } from "../components/ui";
import { CATEGORY, ICONS } from "../editor/FlowNode";
import { ApiError, api } from "../lib/api";
import { useAuth, useCatalogue } from "../lib/auth";
import { number, timeAgo } from "../lib/format";
import { useApi, useDebounced } from "../lib/hooks";
import type { Workflow } from "../lib/types";

function Menu({ items }: { items: { label: string; icon: JSX.Element; onClick: () => void; danger?: boolean }[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={ref} className="relative" onClick={(e) => e.stopPropagation()}>
      <Button size="sm" variant="ghost" aria-label="More actions" aria-expanded={open} icon={<MoreHorizontal size={15} />} onClick={() => setOpen(!open)} />
      {open && (
        <div role="menu" className="absolute right-0 top-full z-20 mt-1 w-40 rounded-md border border-line bg-[#0e1726] p-1 shadow-panel">
          {items.map((item) => (
            <button
              key={item.label}
              role="menuitem"
              className={cx("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-raised", item.danger && "text-[#F87171]")}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function EditModal({ workflow, onClose, onSaved }: { workflow: Workflow; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ name: workflow.name, description: workflow.description, category: workflow.category, folder: workflow.folder });
  const [busy, setBusy] = useState(false);
  const { toast } = useFeedback();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [key]: e.target.value });
  return (
    <Modal
      title="Workflow details"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!form.name.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                await api(`/api/workflows/${workflow.id}`, { method: "PUT", body: form });
                toast("Details updated");
                onSaved();
              } catch (exc) {
                toast((exc as Error).message, "error");
                setBusy(false);
              }
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Name" htmlFor="wf-name">
          <input id="wf-name" className="field" maxLength={160} value={form.name} onChange={set("name")} />
        </Field>
        <Field label="Description" htmlFor="wf-desc">
          <textarea id="wf-desc" className="field min-h-[64px]" maxLength={2000} value={form.description} onChange={set("description")} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Category" htmlFor="wf-cat">
            <input id="wf-cat" className="field" maxLength={60} value={form.category} onChange={set("category")} />
          </Field>
          <Field label="Folder" htmlFor="wf-folder">
            <input id="wf-folder" className="field" maxLength={80} placeholder="None" value={form.folder} onChange={set("folder")} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

export default function Workflows() {
  const navigate = useNavigate();
  const { canEdit } = useAuth();
  const { byType } = useCatalogue();
  const { toast, confirm } = useFeedback();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [folder, setFolder] = useState("");
  const [sort, setSort] = useState("updated");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Workflow | null>(null);
  const debounced = useDebounced(search);
  const { data, error, loading, reload } = useApi<any>("/api/workflows", { search: debounced, status, folder, sort, page, page_size: 12 });

  const create = async () => {
    try {
      const wf = await api("/api/workflows", { method: "POST", body: { name: "Untitled workflow" } });
      navigate(`/workflows/${wf.id}`);
    } catch (exc) {
      toast((exc as Error).message, "error");
    }
  };

  const remove = async (wf: Workflow) => {
    const ok = await confirm({ title: `Delete "${wf.name}"?`, body: "This also deletes its versions and execution history. It cannot be undone.", confirm: "Delete workflow", danger: true });
    if (!ok) return;
    try {
      await api(`/api/workflows/${wf.id}`, { method: "DELETE" });
      toast("Workflow deleted");
      reload(true);
    } catch (exc) {
      toast(exc instanceof ApiError ? exc.message : "Could not delete", "error");
    }
  };

  const items: Workflow[] = data?.items || [];
  const filtering = !!(search || status || folder);

  return (
    <PageBody>
      <PageHeader
        title="My Workflows"
        description="Create, organise and open your automations."
        actions={
          <>
            <Button icon={<Sparkles size={14} />} onClick={() => navigate("/ai")}>
              Generate with AI
            </Button>
            <Button variant="primary" disabled={!canEdit} icon={<Plus size={14} />} onClick={create}>
              New workflow
            </Button>
          </>
        }
      />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search size={13} className="absolute left-2 top-2 text-faint" />
          <input
            aria-label="Search workflows"
            className="field pl-7"
            placeholder="Search workflows"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <select aria-label="Filter by status" className="field w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
        <select aria-label="Filter by folder" className="field w-auto" value={folder} onChange={(e) => { setFolder(e.target.value); setPage(1); }}>
          <option value="">All folders</option>
          {(data?.folders || []).map((f: string) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <select aria-label="Sort" className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="updated">Recently updated</option>
          <option value="created">Recently created</option>
          <option value="name">Name</option>
        </select>
      </div>
      {error && <ErrorState message={error} retry={() => reload()} />}
      {loading && !data ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<WorkflowIcon size={30} />}
            title={filtering ? "No workflows match your filters" : "No workflows yet"}
            action={
              !filtering && (
                <div className="flex gap-2">
                  <Button variant="primary" disabled={!canEdit} icon={<Plus size={14} />} onClick={create}>
                    New workflow
                  </Button>
                  <Button onClick={() => navigate("/templates")}>Browse templates</Button>
                </div>
              )
            }
          >
            {filtering ? "Try a different search." : "Build one on the canvas, start from a template, or describe it to the AI builder."}
          </EmptyState>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((wf) => (
            <article
              key={wf.id}
              tabIndex={0}
              onClick={() => navigate(`/workflows/${wf.id}`)}
              onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && navigate(`/workflows/${wf.id}`)}
              className="card flex cursor-pointer flex-col p-3.5 transition-colors hover:border-lineStrong"
              data-testid="workflow-card"
            >
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <h2 className="truncate text-sm font-semibold">{wf.name}</h2>
                  <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-faint">
                    <span>{wf.category}</span>
                    {wf.folder && (
                      <>
                        <span>·</span>
                        <span>{wf.folder}</span>
                      </>
                    )}
                  </div>
                </div>
                {wf.is_demo && <DemoBadge label="Demo" />}
                <Badge tone={wf.is_active ? "success" : "neutral"}>{wf.is_active ? "Active" : "Inactive"}</Badge>
                {canEdit && (
                  <Menu
                    items={[
                      { label: "Rename and details", icon: <Pencil size={13} />, onClick: () => setEditing(wf) },
                      { label: "Move to folder", icon: <FolderInput size={13} />, onClick: () => setEditing(wf) },
                      {
                        label: "Duplicate",
                        icon: <Copy size={13} />,
                        onClick: async () => {
                          await api(`/api/workflows/${wf.id}/duplicate`, { method: "POST" });
                          toast("Workflow duplicated");
                          reload(true);
                        },
                      },
                      { label: "Delete", icon: <Trash2 size={13} />, danger: true, onClick: () => remove(wf) },
                    ]}
                  />
                )}
              </div>
              <p className="mt-2 line-clamp-2 min-h-[36px] text-xs text-muted">{wf.description || "No description"}</p>
              <div className="mt-3 flex items-center gap-1">
                {wf.node_types.slice(0, 7).map((type, i) => {
                  const spec = byType[type];
                  const Icon = spec && ICONS[spec.icon];
                  return (
                    <span key={i} title={spec?.label} className={cx("flex h-6 w-6 items-center justify-center rounded", spec ? CATEGORY[spec.category].tile : "bg-raised")}>
                      {Icon && <Icon size={12} />}
                    </span>
                  );
                })}
                {wf.node_count > 7 && <span className="ml-1 text-2xs text-faint">+{wf.node_count - 7}</span>}
                {wf.node_count === 0 && <span className="text-2xs text-faint">Empty canvas</span>}
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-line pt-2 text-2xs text-faint">
                <span className="tabular">
                  {number(wf.runs)} runs{wf.failures ? ` · ${wf.failures} failed` : ""}
                </span>
                <span>Updated {timeAgo(wf.updated_at)}</span>
              </div>
            </article>
          ))}
        </div>
      )}
      {data && data.total > 12 && (
        <div className="card mt-3 overflow-hidden">
          <Pagination page={page} pageSize={12} total={data.total} onChange={setPage} />
        </div>
      )}
      {editing && (
        <EditModal
          workflow={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload(true);
          }}
        />
      )}
    </PageBody>
  );
}
