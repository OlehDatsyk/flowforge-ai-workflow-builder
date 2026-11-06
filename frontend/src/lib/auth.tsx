import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, session } from "./api";
import type { NodeSpec, User } from "./types";

interface AuthValue {
  user: User | null;
  loading: boolean;
  workspaceId: string;
  role: string;
  canEdit: boolean;
  isAdmin: boolean;
  signIn: (user: User) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  switchWorkspace: (id: string) => void;
}

const AuthContext = createContext<AuthValue>(null as unknown as AuthValue);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspaceId, setWorkspaceId] = useState(session.getWorkspace());

  const applyUser = useCallback((next: User) => {
    session.setCsrf(next.csrf_token);
    setUser(next);
    const known = next.workspaces.find((w) => w.id === session.getWorkspace());
    const id = known ? known.id : next.workspaces[0]?.id || "";
    session.setWorkspace(id);
    setWorkspaceId(id);
  }, []);

  const refresh = useCallback(async () => {
    applyUser(await api<User>("/api/auth/me"));
  }, [applyUser]);

  useEffect(() => {
    session.onUnauthorized(() => setUser(null));
    refresh()
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [refresh]);

  const value = useMemo<AuthValue>(() => {
    const role = user?.workspaces.find((w) => w.id === workspaceId)?.role || "viewer";
    return {
      user,
      loading,
      workspaceId,
      role,
      canEdit: role !== "viewer",
      isAdmin: role === "owner" || role === "admin",
      signIn: applyUser,
      signOut: async () => {
        await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
        session.setCsrf("");
        setUser(null);
      },
      refresh,
      switchWorkspace: (id) => {
        session.setWorkspace(id);
        setWorkspaceId(id);
      },
    };
  }, [user, loading, workspaceId, applyUser, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

// ------------------------------------------------------------- node catalogue
const CatalogueContext = createContext<{ specs: NodeSpec[]; byType: Record<string, NodeSpec> }>({ specs: [], byType: {} });

export function CatalogueProvider({ children }: { children: ReactNode }) {
  const [specs, setSpecs] = useState<NodeSpec[]>([]);
  useEffect(() => {
    api<NodeSpec[]>("/api/nodes").then(setSpecs).catch(() => setSpecs([]));
  }, []);
  const value = useMemo(() => ({ specs, byType: Object.fromEntries(specs.map((s) => [s.type, s])) }), [specs]);
  return <CatalogueContext.Provider value={value}>{children}</CatalogueContext.Provider>;
}

export const useCatalogue = () => useContext(CatalogueContext);
