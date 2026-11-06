import {
  Activity,
  BarChart3,
  ChevronsUpDown,
  KeyRound,
  LayoutDashboard,
  LayoutTemplate,
  LogOut,
  Menu,
  Plug,
  Settings,
  Sparkles,
  UserRound,
  Workflow,
  X,
} from "lucide-react";
import { ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { cx, DemoBadge, Tip } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/workflows", label: "My Workflows", icon: Workflow },
  { to: "/templates", label: "Workflow Templates", icon: LayoutTemplate },
  { to: "/ai", label: "AI Workflow Builder", icon: Sparkles },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/executions", label: "Execution History", icon: Activity },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/credentials", label: "Credentials", icon: KeyRound },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Logo({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" width={26} height={26} className="shrink-0" />
      {!compact && <span className="text-[15px] font-semibold tracking-tight">FlowForge<span className="ml-1 text-primary-hover">AI</span></span>}
    </div>
  );
}

function Popover({ button, children, open, setOpen }: { button: ReactNode; children: ReactNode; open: boolean; setOpen: (v: boolean) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [setOpen]);
  return (
    <div ref={ref} className="relative">
      {button}
      {open && <div className="absolute bottom-full left-0 z-40 mb-1 w-60 rounded-md border border-line bg-[#0e1726] p-1 shadow-panel">{children}</div>}
    </div>
  );
}

function Sidebar({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { user, workspaceId, switchWorkspace, signOut } = useAuth();
  const navigate = useNavigate();
  const [wsOpen, setWsOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const workspace = user?.workspaces.find((w) => w.id === workspaceId);

  return (
    <aside className={cx("flex h-full shrink-0 flex-col border-r border-line bg-side", collapsed ? "w-[56px]" : "w-[232px]")}>
      <div className={cx("flex h-[52px] items-center border-b border-line", collapsed ? "justify-center" : "px-4")}>
        <NavLink to="/" aria-label="FlowForge AI home" onClick={onNavigate}>
          <Logo compact={collapsed} />
        </NavLink>
      </div>
      <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {NAV.map((item) => {
          const link = (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              aria-label={item.label}
              className={({ isActive }) =>
                cx(
                  "flex items-center gap-2.5 rounded-md text-[13px] font-medium transition-colors",
                  collapsed ? "h-9 w-10 justify-center" : "px-2.5 py-[7px]",
                  isActive ? "bg-primary-soft text-ink" : "text-muted hover:bg-raised hover:text-ink",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon size={16} className={isActive ? "text-primary-hover" : ""} />
                  {!collapsed && item.label}
                </>
              )}
            </NavLink>
          );
          return collapsed ? (
            <Tip key={item.to} text={item.label} side="right">
              {link}
            </Tip>
          ) : (
            link
          );
        })}
      </nav>
      <div className="space-y-1 border-t border-line p-2">
        <Popover
          open={wsOpen}
          setOpen={setWsOpen}
          button={
            <button aria-label="Switch workspace" onClick={() => setWsOpen(!wsOpen)} className={cx("flex w-full items-center gap-2 rounded-md py-1.5 text-left transition-colors hover:bg-raised", collapsed ? "justify-center" : "px-2")}>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-action-soft text-2xs font-bold text-[#93C5FD]">{workspace?.name?.[0]?.toUpperCase() || "W"}</span>
              {!collapsed && (
                <>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium">{workspace?.name || "Workspace"}</span>
                    <span className="block text-2xs capitalize text-faint">{workspace?.role}</span>
                  </span>
                  <ChevronsUpDown size={13} className="text-faint" />
                </>
              )}
            </button>
          }
        >
          <div className="px-2 py-1 text-2xs font-semibold uppercase tracking-wide text-faint">Workspaces</div>
          {user?.workspaces.map((w) => (
            <button
              key={w.id}
              onClick={() => {
                switchWorkspace(w.id);
                setWsOpen(false);
                navigate("/");
              }}
              className={cx("w-full truncate rounded px-2 py-1.5 text-left text-xs hover:bg-raised", w.id === workspaceId && "text-primary-hover")}
            >
              {w.name}
            </button>
          ))}
          <button
            onClick={() => {
              setWsOpen(false);
              navigate("/settings?tab=workspace");
            }}
            className="mt-1 w-full rounded border-t border-line px-2 py-1.5 text-left text-xs text-muted hover:bg-raised hover:text-ink"
          >
            Manage workspaces
          </button>
        </Popover>
        <Popover
          open={userOpen}
          setOpen={setUserOpen}
          button={
            <button aria-label="Account menu" onClick={() => setUserOpen(!userOpen)} className={cx("flex w-full items-center gap-2 rounded-md py-1.5 text-left transition-colors hover:bg-raised", collapsed ? "justify-center" : "px-2")}>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-raised text-muted">
                <UserRound size={13} />
              </span>
              {!collapsed && (
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">{user?.name}</span>
                  <span className="block truncate text-2xs text-faint">{user?.email}</span>
                </span>
              )}
            </button>
          }
        >
          <button
            onClick={() => {
              setUserOpen(false);
              navigate("/settings?tab=account");
            }}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-raised"
          >
            <UserRound size={13} /> Account settings
          </button>
          <button onClick={signOut} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-raised">
            <LogOut size={13} /> Log out
          </button>
        </Popover>
      </div>
    </aside>
  );
}

export function AppLayout() {
  const { pathname } = useLocation();
  const { user, workspaceId } = useAuth();
  const inEditor = /^\/workflows\/[^/]+/.test(pathname);
  const [drawer, setDrawer] = useState(false);
  const workspace = user?.workspaces.find((w) => w.id === workspaceId);
  const title = NAV.find((n) => (n.end ? pathname === n.to : pathname.startsWith(n.to)))?.label || "FlowForge AI";

  return (
    <div className="flex h-full overflow-hidden">
      <div className="hidden md:block">
        <Sidebar collapsed={inEditor} />
      </div>
      {drawer && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <Sidebar collapsed={false} onNavigate={() => setDrawer(false)} />
          <button aria-label="Close menu" className="flex-1 bg-black/50" onClick={() => setDrawer(false)}>
            <X className="ml-3 text-white" size={20} />
          </button>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {!inEditor && (
          <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-line bg-side/60 px-4">
            <button aria-label="Open menu" className="rounded p-1 text-muted hover:bg-raised md:hidden" onClick={() => setDrawer(true)}>
              <Menu size={18} />
            </button>
            <div className="flex min-w-0 items-center gap-1.5 text-[13px]">
              <span className="truncate text-faint">{workspace?.name}</span>
              <span className="text-faint">/</span>
              <span className="truncate font-medium">{title}</span>
            </div>
            <div className="ml-auto flex items-center gap-2">{user?.is_demo && <DemoBadge label="Demo workspace" />}</div>
          </header>
        )}
        {inEditor && (
          <button aria-label="Open menu" className="fixed left-2 top-2 z-30 rounded border border-line bg-surface p-1.5 text-muted md:hidden" onClick={() => setDrawer(true)}>
            <Menu size={16} />
          </button>
        )}
        <main key={workspaceId} className={cx("min-h-0 flex-1", inEditor ? "overflow-hidden" : "overflow-y-auto")}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function PageBody({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1400px] p-4 md:p-6">{children}</div>;
}
