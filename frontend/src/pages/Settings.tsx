import { FlaskConical, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageBody } from "../components/Layout";
import { Badge, Button, EmptyState, Field, Notice, PageHeader, Pagination, Tabs, useFeedback } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime } from "../lib/format";
import { useApi } from "../lib/hooks";

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="card p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Account() {
  const { user, refresh, signOut } = useAuth();
  const { toast } = useFeedback();
  const [name, setName] = useState(user?.name || "");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  return (
    <div className="max-w-xl space-y-3">
      {user?.is_demo && <Notice tone="demo">The shared demo account's profile and password cannot be changed.</Notice>}
      <Section title="Profile">
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/api/auth/me", { method: "PATCH", body: { name } });
              await refresh();
              toast("Profile updated");
            } catch (exc) {
              toast((exc as Error).message, "error");
            }
          }}
        >
          <Field label="Email">
            <input className="field" readOnly disabled value={user?.email || ""} />
          </Field>
          <Field label="Name" htmlFor="profile-name">
            <input id="profile-name" className="field" maxLength={120} disabled={user?.is_demo} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" disabled={user?.is_demo || !name.trim()}>
            Save profile
          </Button>
        </form>
      </Section>
      <Section title="Change password" description="This signs out your other sessions.">
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/api/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
              setCurrent("");
              setNext("");
              toast("Password changed");
            } catch (exc) {
              toast((exc as Error).message, "error");
            }
          }}
        >
          <Field label="Current password" htmlFor="pw-current">
            <input id="pw-current" type="password" autoComplete="current-password" className="field" disabled={user?.is_demo} value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="New password" htmlFor="pw-new" hint="At least 10 characters.">
            <input id="pw-new" type="password" minLength={10} autoComplete="new-password" className="field" disabled={user?.is_demo} value={next} onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Button type="submit" disabled={user?.is_demo || !current || next.length < 10}>
            Change password
          </Button>
        </form>
      </Section>
      <Section title="Session">
        <Button onClick={signOut}>Log out</Button>
      </Section>
    </div>
  );
}

function WorkspaceTab() {
  const { user, workspaceId, role, isAdmin, refresh, switchWorkspace } = useAuth();
  const { toast, confirm } = useFeedback();
  const navigate = useNavigate();
  const current = user?.workspaces.find((w) => w.id === workspaceId);
  const info = useApi<any>("/api/workspaces/current");
  const members = useApi<any[]>("/api/workspaces/current/members");
  const [name, setName] = useState(current?.name || "");
  const [newName, setNewName] = useState("");
  const [email, setEmail] = useState("");
  const [memberRole, setMemberRole] = useState("editor");
  const fail = (exc: unknown) => toast((exc as Error).message, "error");
  const demo = user?.is_demo;
  return (
    <div className="max-w-2xl space-y-3">
      <Section title="This workspace" description={`Your role: ${role}`}>
        <form
          className="flex gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/api/workspaces/current", { method: "PATCH", body: { name } });
              await refresh();
              toast("Workspace renamed");
            } catch (exc) {
              fail(exc);
            }
          }}
        >
          <input aria-label="Workspace name" className="field" maxLength={120} disabled={!isAdmin || demo} value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" disabled={!isAdmin || demo || !name.trim()}>
            Rename
          </Button>
        </form>
      </Section>
      <Section title="Members">
        <div className="divide-y divide-line rounded-md border border-line">
          {(members.data || []).map((m) => (
            <div key={m.user_id} className="flex items-center gap-2 px-3 py-2 text-[13px]" data-testid="member-row">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{m.name}</div>
                <div className="truncate text-2xs text-faint">{m.email}</div>
              </div>
              {m.role === "owner" || !isAdmin ? (
                <Badge>{m.role}</Badge>
              ) : (
                <>
                  <select
                    aria-label={`Role for ${m.name}`}
                    className="field w-auto"
                    value={m.role}
                    onChange={async (e) => {
                      await api(`/api/workspaces/current/members/${m.user_id}`, { method: "PATCH", body: { role: e.target.value } }).catch(fail);
                      members.reload(true);
                    }}
                  >
                    {["admin", "editor", "viewer"].map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Remove ${m.name}`}
                    icon={<Trash2 size={13} />}
                    onClick={async () => {
                      if (await confirm({ title: `Remove ${m.name}?`, body: "They lose access to this workspace.", confirm: "Remove", danger: true })) {
                        await api(`/api/workspaces/current/members/${m.user_id}`, { method: "DELETE" }).catch(fail);
                        members.reload(true);
                      }
                    }}
                  />
                </>
              )}
            </div>
          ))}
        </div>
        {isAdmin && !demo && (
          <form
            className="mt-3 flex flex-wrap gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api("/api/workspaces/current/members", { method: "POST", body: { email, role: memberRole } });
                setEmail("");
                members.reload(true);
                toast("Member added");
              } catch (exc) {
                fail(exc);
              }
            }}
          >
            <input aria-label="Member email" type="email" required className="field min-w-[200px] flex-1" placeholder="colleague@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            <select aria-label="Member role" className="field w-auto" value={memberRole} onChange={(e) => setMemberRole(e.target.value)}>
              {["editor", "viewer", "admin"].map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <Button type="submit" icon={<Plus size={13} />}>
              Add member
            </Button>
          </form>
        )}
      </Section>
      <Section title="Demonstration data" description="Example workflows and generated execution records, labelled as demo everywhere.">
        <div className="flex flex-wrap items-center gap-2">
          {info.data?.demo_workflows ? (
            <>
              <Badge tone="cyan" icon={<FlaskConical size={11} />}>
                {info.data.demo_workflows} workflows, {info.data.demo_executions} records
              </Badge>
              {!demo && isAdmin && (
                <Button
                  size="sm"
                  onClick={async () => {
                    if (await confirm({ title: "Remove demo data?", body: "Deletes the demo workflows and every execution of them, including real runs of those workflows. Your own workflows are untouched.", confirm: "Remove", danger: true })) {
                      await api("/api/workspaces/current/demo-data", { method: "DELETE" }).catch(fail);
                      info.reload(true);
                      toast("Demo data removed");
                    }
                  }}
                >
                  Remove demo data
                </Button>
              )}
            </>
          ) : (
            <Button
              size="sm"
              disabled={!isAdmin}
              icon={<FlaskConical size={13} />}
              onClick={async () => {
                await api("/api/workspaces/current/demo-data", { method: "POST" }).catch(fail);
                info.reload(true);
                toast("Demo data loaded");
              }}
            >
              Load demo data
            </Button>
          )}
        </div>
      </Section>
      {!demo && (
        <Section title="Create another workspace">
          <form
            className="flex gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const created = await api("/api/workspaces", { method: "POST", body: { name: newName } });
                await refresh();
                switchWorkspace(created.id);
                setNewName("");
                toast("Workspace created");
                navigate("/");
              } catch (exc) {
                fail(exc);
              }
            }}
          >
            <input aria-label="New workspace name" className="field" maxLength={120} placeholder="Workspace name" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <Button type="submit" disabled={!newName.trim()}>
              Create
            </Button>
          </form>
        </Section>
      )}
      {role === "owner" && !demo && (user?.workspaces.length || 0) > 1 && (
        <Section title="Delete this workspace" description="Permanently deletes its workflows, executions and credentials.">
          <Button
            variant="danger"
            onClick={async () => {
              if (await confirm({ title: `Delete "${current?.name}"?`, body: "Everything in this workspace is permanently deleted.", confirm: "Delete workspace", danger: true })) {
                try {
                  await api("/api/workspaces/current", { method: "DELETE" });
                  const other = user?.workspaces.find((w) => w.id !== workspaceId);
                  if (other) switchWorkspace(other.id);
                  await refresh();
                  navigate("/");
                } catch (exc) {
                  fail(exc);
                }
              }
            }}
          >
            Delete workspace
          </Button>
        </Section>
      )}
    </div>
  );
}

function AuditLog() {
  const [page, setPage] = useState(1);
  const { data, error } = useApi<any>("/api/audit-logs", { page, page_size: 20 });
  if (error) return <Notice tone="warning">{error}</Notice>;
  return (
    <section className="card overflow-hidden">
      {data?.items.length === 0 ? (
        <EmptyState title="No activity recorded yet" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line">
                {["When", "Who", "Action", "Target", "IP"].map((h) => (
                  <th key={h} className="th">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.items.map((row: any) => (
                <tr key={row.id} className="border-b border-line/50 last:border-0">
                  <td className="td whitespace-nowrap text-muted">{dateTime(row.created_at)}</td>
                  <td className="td">{row.user}</td>
                  <td className="td font-mono text-xs">{row.action}</td>
                  <td className="td max-w-[280px] truncate text-muted" title={JSON.stringify(row.details)}>
                    {row.details?.name || row.entity_type} {row.entity_id && <span className="font-mono text-2xs text-faint">{row.entity_id.slice(0, 14)}</span>}
                  </td>
                  <td className="td font-mono text-2xs text-faint">{row.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination page={page} pageSize={20} total={data.total} onChange={setPage} />}
    </section>
  );
}

export default function Settings() {
  const [params, setParams] = useSearchParams();
  const { isAdmin } = useAuth();
  const tab = (params.get("tab") as "account" | "workspace" | "audit") || "account";
  return (
    <PageBody>
      <PageHeader title="Settings" description="Your account, workspace and activity log." />
      <div className="mb-4">
        <Tabs
          value={tab}
          onChange={(id) => setParams({ tab: id }, { replace: true })}
          tabs={[{ id: "account", label: "Account" }, { id: "workspace", label: "Workspace" }, ...(isAdmin ? [{ id: "audit" as const, label: "Audit log" }] : [])]}
        />
      </div>
      {tab === "account" && <Account />}
      {tab === "workspace" && <WorkspaceTab />}
      {tab === "audit" && <AuditLog />}
    </PageBody>
  );
}
