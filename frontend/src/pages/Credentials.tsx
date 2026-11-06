import { KeyRound, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { PageBody } from "../components/Layout";
import { Badge, Button, EmptyState, ErrorState, Field, Modal, Notice, PageHeader, TableSkeleton, useFeedback } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";

export function CredentialModal({ existing, types, initialType, onClose, onSaved }: { existing?: any; types: Record<string, any>; initialType?: string; onClose: () => void; onSaved: (credential: any) => void }) {
  const { toast } = useFeedback();
  const [name, setName] = useState(existing?.name || "");
  const [type, setType] = useState(existing?.type || initialType || "bearer_token");
  const [data, setData] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fields = types[type]?.fields || [];
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = existing ? await api(`/api/credentials/${existing.id}`, { method: "PATCH", body: { name, data } }) : await api("/api/credentials", { method: "POST", body: { name, type, data } });
      toast(existing ? "Credential updated" : "Credential saved");
      onSaved(result);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Could not save");
      setBusy(false);
    }
  };
  return (
    <Modal
      title={existing ? `Edit ${existing.name}` : "Add credential"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save(); }} autoComplete="off">
        {error && <Notice tone="warning">{error}</Notice>}
        <Field label="Name" htmlFor="cred-name">
          <input id="cred-name" className="field" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        {!existing && (
          <Field label="Type" htmlFor="cred-type">
            <select id="cred-type" className="field" value={type} onChange={(e) => { setType(e.target.value); setData({}); }}>
              {Object.entries(types).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.label}
                </option>
              ))}
            </select>
          </Field>
        )}
        {fields.map((f: any) => (
          <Field key={f.key} label={<>{f.label}{f.required && !existing && <span className="ml-0.5 text-[#F87171]">*</span>}</>} htmlFor={`cred-${f.key}`} hint={existing?.masked?.[f.key] ? `Current: ${existing.masked[f.key]}. Leave blank to keep it.` : undefined}>
            <input id={`cred-${f.key}`} className="field" type={f.secret ? "password" : "text"} autoComplete={f.secret ? "new-password" : "off"} placeholder={f.placeholder} value={data[f.key] || ""} onChange={(e) => setData({ ...data, [f.key]: e.target.value })} />
          </Field>
        ))}
        <p className="flex items-center gap-1.5 text-2xs text-faint">
          <Lock size={11} /> Encrypted before storage. Secret values are never sent back to the browser.
        </p>
      </form>
    </Modal>
  );
}

export default function Credentials() {
  const { isAdmin, user } = useAuth();
  const { toast, confirm } = useFeedback();
  const { data, error, loading, reload } = useApi<any[]>("/api/credentials");
  const types = useApi<Record<string, any>>("/api/credentials/types");
  const [modal, setModal] = useState<{ existing?: any } | null>(null);
  const remove = async (c: any) => {
    const ok = await confirm({ title: `Delete "${c.name}"?`, body: c.used_by ? `${c.used_by} workflow(s) use it and will stop validating until you choose another credential.` : "No workflow uses this credential.", confirm: "Delete", danger: true });
    if (!ok) return;
    try {
      await api(`/api/credentials/${c.id}`, { method: "DELETE" });
      toast("Credential deleted");
      reload(true);
    } catch (exc) {
      toast((exc as Error).message, "error");
    }
  };
  return (
    <PageBody>
      <PageHeader
        title="Credentials"
        description="Secrets used by nodes and integrations. Workflows only store a reference to these, never the value."
        actions={
          <Button variant="primary" disabled={!isAdmin || user?.is_demo} title={user?.is_demo ? "Register for your own workspace to store credentials" : undefined} icon={<Plus size={14} />} onClick={() => setModal({})}>
            Add credential
          </Button>
        }
      />
      {user?.is_demo && (
        <div className="mb-3">
          <Notice tone="demo">The shared demo workspace cannot store credentials. Register for your own workspace to add them.</Notice>
        </div>
      )}
      {error && <ErrorState message={error} retry={() => reload()} />}
      <section className="card overflow-hidden">
        {loading ? (
          <TableSkeleton rows={4} />
        ) : !data?.length ? (
          <EmptyState icon={<KeyRound size={30} />} title="No credentials yet" action={isAdmin && !user?.is_demo ? <Button icon={<Plus size={14} />} onClick={() => setModal({})}>Add credential</Button> : undefined}>
            Add an SMTP server, API token or AI provider key to use them in workflows.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-line">
                  {["Name", "Type", "Values", "Used by", "Updated", ""].map((h, i) => (
                    <th key={i} className="th">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((c) => (
                  <tr key={c.id} className="border-b border-line/50 last:border-0" data-testid="credential-row">
                    <td className="td font-medium">{c.name}</td>
                    <td className="td">
                      <Badge>{c.type_label}</Badge>
                    </td>
                    <td className="td font-mono text-xs text-muted">
                      {Object.entries(c.masked).map(([k, v]) => (
                        <div key={k}>
                          {k}: {String(v)}
                        </div>
                      ))}
                    </td>
                    <td className="td tabular text-muted">{c.used_by} workflow{c.used_by === 1 ? "" : "s"}</td>
                    <td className="td whitespace-nowrap text-muted">{timeAgo(c.updated_at)}</td>
                    <td className="td whitespace-nowrap text-right">
                      {isAdmin && (
                        <>
                          <Button size="sm" variant="ghost" aria-label={`Edit ${c.name}`} icon={<Pencil size={13} />} onClick={() => setModal({ existing: c })} />
                          <Button size="sm" variant="ghost" aria-label={`Delete ${c.name}`} icon={<Trash2 size={13} />} onClick={() => remove(c)} />
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {modal && types.data && (
        <CredentialModal
          existing={modal.existing}
          types={types.data}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            reload(true);
          }}
        />
      )}
    </PageBody>
  );
}
