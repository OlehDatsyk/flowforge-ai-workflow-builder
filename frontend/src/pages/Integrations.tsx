import { CheckCircle2, ChevronRight, Database, Plug, Plus, Trash2, Unplug, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageBody } from "../components/Layout";
import { Badge, Button, cx, EmptyState, ErrorState, Field, JsonView, Modal, PageHeader, Pagination, Skeleton, Tabs, useFeedback } from "../components/ui";
import { ICONS } from "../editor/FlowNode";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";
import { CredentialModal } from "./Credentials";

function ConnectModal({ item, onClose, onDone }: { item: any; onClose: () => void; onDone: () => void }) {
  const { toast } = useFeedback();
  const { user } = useAuth();
  const creds = useApi<any[]>("/api/credentials");
  const types = useApi<Record<string, any>>("/api/credentials/types");
  const options = (creds.data || []).filter((c) => item.credential_types.includes(c.type));
  const [selected, setSelected] = useState(item.credential_id || "");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <Modal
        title={`Connect ${item.name}`}
        onClose={onClose}
        footer={
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              loading={busy}
              disabled={!selected}
              onClick={async () => {
                setBusy(true);
                try {
                  await api(`/api/integrations/${item.provider}`, { method: "PUT", body: { credential_id: selected } });
                  toast(`${item.name} connected`);
                  onDone();
                } catch (exc) {
                  toast((exc as Error).message, "error");
                  setBusy(false);
                }
              }}
            >
              Connect
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-[13px] text-muted">{item.description}</p>
          <Field label="Credential" htmlFor="connect-cred">
            <select id="connect-cred" className="field" value={selected} onChange={(e) => setSelected(e.target.value)}>
              <option value="">Choose...</option>
              {options.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Button size="sm" disabled={user?.is_demo} icon={<Plus size={13} />} onClick={() => setAdding(true)}>
            New credential
          </Button>
          {user?.is_demo && <p className="text-2xs text-faint">The shared demo workspace cannot store credentials.</p>}
        </div>
      </Modal>
      {adding && types.data && (
        <CredentialModal
          types={types.data}
          initialType={item.credential_types[0]}
          onClose={() => setAdding(false)}
          onSaved={(credential) => {
            setAdding(false);
            creds.reload(true);
            setSelected(credential.id);
          }}
        />
      )}
    </>
  );
}

function Catalogue() {
  const { isAdmin } = useAuth();
  const { toast, confirm } = useFeedback();
  const { data, error, loading, reload } = useApi<any[]>("/api/integrations");
  const [connecting, setConnecting] = useState<any>(null);
  const [testing, setTesting] = useState<string | null>(null);
  if (error) return <ErrorState message={error} retry={() => reload()} />;
  if (loading) {
    return (
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-40" />
        ))}
      </div>
    );
  }
  return (
    <>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {data?.map((item) => {
          const Icon = ICONS[item.icon] || Plug;
          const connected = item.status === "connected";
          return (
            <article key={item.provider} className="card flex flex-col p-3.5" data-testid={`integration-${item.provider}`}>
              <div className="flex items-start gap-2.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-action-soft text-[#93C5FD]">
                  <Icon size={17} />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold">{item.name}</h2>
                  <div className="text-2xs text-faint">{item.category}</div>
                </div>
                {item.builtin ? <Badge tone="success">Built in</Badge> : connected ? <Badge tone="success">{item.source === "server_environment" ? "Server key" : "Connected"}</Badge> : <Badge>Not configured</Badge>}
              </div>
              <p className="mt-2 flex-1 text-xs text-muted">{item.description}</p>
              {item.last_test_at && (
                <div className={cx("mt-2 flex items-start gap-1.5 text-2xs", item.last_test_ok ? "text-[#4ADE80]" : "text-[#F87171]")}>
                  {item.last_test_ok ? <CheckCircle2 size={12} className="mt-px shrink-0" /> : <XCircle size={12} className="mt-px shrink-0" />}
                  <span>
                    {item.last_test_message} ({timeAgo(item.last_test_at)})
                  </span>
                </div>
              )}
              {!item.builtin && isAdmin && (
                <div className="mt-3 flex gap-1.5">
                  <Button size="sm" variant={connected ? "secondary" : "primary"} onClick={() => setConnecting(item)}>
                    {item.source === "credential" ? "Change" : "Connect"}
                  </Button>
                  {connected && (
                    <Button
                      size="sm"
                      loading={testing === item.provider}
                      onClick={async () => {
                        setTesting(item.provider);
                        try {
                          const r = await api(`/api/integrations/${item.provider}/test`, { method: "POST" });
                          toast(r.message, r.ok ? "success" : "error");
                          reload(true);
                        } catch (exc) {
                          toast((exc as Error).message, "error");
                        } finally {
                          setTesting(null);
                        }
                      }}
                    >
                      Test connection
                    </Button>
                  )}
                  {item.source === "credential" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Disconnect ${item.name}`}
                      icon={<Unplug size={13} />}
                      onClick={async () => {
                        if (await confirm({ title: `Disconnect ${item.name}?`, body: "The credential is kept. Nodes relying on this connection stop using it.", confirm: "Disconnect" })) {
                          await api(`/api/integrations/${item.provider}`, { method: "DELETE" });
                          reload(true);
                        }
                      }}
                    />
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-faint">Only integrations that really work are listed. Other services can be reached through the HTTP Request node if they have a public API.</p>
      {connecting && (
        <ConnectModal
          item={connecting}
          onClose={() => setConnecting(null)}
          onDone={() => {
            setConnecting(null);
            reload(true);
          }}
        />
      )}
    </>
  );
}

function DataStore() {
  const { canEdit } = useAuth();
  const { toast, confirm } = useFeedback();
  const { data, error, loading, reload } = useApi<any[]>("/api/data/collections");
  const [collection, setCollection] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const records = useApi<any>(collection ? `/api/data/collections/${encodeURIComponent(collection)}` : null, { page, page_size: 10 });
  const [viewing, setViewing] = useState<any>(null);
  if (error) return <ErrorState message={error} retry={() => reload()} />;
  if (loading) return <Skeleton className="h-60 w-full" />;
  if (!data?.length) {
    return (
      <div className="card">
        <EmptyState icon={<Database size={30} />} title="No records yet">
          Records written by a Database Operation node appear here.
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="grid gap-3 md:grid-cols-[240px_minmax(0,1fr)]">
      <div className="card self-start p-1.5">
        {data.map((c) => (
          <button key={c.name} onClick={() => { setCollection(c.name); setPage(1); }} className={cx("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-raised", collection === c.name && "bg-primary-soft")}>
            <span className="min-w-0 flex-1 truncate font-medium">{c.name}</span>
            <span className="tabular text-faint">{c.count}</span>
            <ChevronRight size={12} className="text-faint" />
          </button>
        ))}
      </div>
      <div className="card overflow-hidden">
        {!collection ? (
          <div className="p-8 text-center text-xs text-faint">Select a collection.</div>
        ) : records.loading && !records.data ? (
          <Skeleton className="m-3 h-40" />
        ) : (
          <>
            <table className="w-full text-xs">
              <tbody>
                {(records.data?.items || []).map((r: any) => (
                  <tr key={r.id} className="border-b border-line/50 hover:bg-raised/50">
                    <td className="td max-w-0 w-full cursor-pointer truncate font-mono text-[11px] text-muted" onClick={() => setViewing(r)} title="View record">
                      {JSON.stringify(r.data)}
                    </td>
                    <td className="td whitespace-nowrap text-faint">{dateTime(r.created_at)}</td>
                    <td className="td">
                      {canEdit && (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label="Delete record"
                          icon={<Trash2 size={12} />}
                          onClick={async () => {
                            if (await confirm({ title: "Delete this record?", confirm: "Delete", danger: true, body: "This cannot be undone." })) {
                              await api(`/api/data/records/${r.id}`, { method: "DELETE" });
                              toast("Record deleted");
                              records.reload(true);
                              reload(true);
                            }
                          }}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination page={page} pageSize={10} total={records.data?.total || 0} onChange={setPage} />
          </>
        )}
      </div>
      {viewing && (
        <Modal title="Record" onClose={() => setViewing(null)}>
          <JsonView value={viewing.data} maxHeight="max-h-96" />
          {viewing.execution_id && (
            <Link className="mt-2 inline-block text-xs text-primary-hover hover:underline" to={`/executions/${viewing.execution_id}`}>
              Written by this execution
            </Link>
          )}
        </Modal>
      )}
    </div>
  );
}

export default function Integrations() {
  const [tab, setTab] = useState<"catalogue" | "data">("catalogue");
  return (
    <PageBody>
      <PageHeader title="Integrations" description="Connect the services your workflows use, and browse the built-in data store." />
      <div className="mb-4">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "catalogue", label: "Connections" },
            { id: "data", label: "Data store" },
          ]}
        />
      </div>
      {tab === "catalogue" ? <Catalogue /> : <DataStore />}
    </PageBody>
  );
}
