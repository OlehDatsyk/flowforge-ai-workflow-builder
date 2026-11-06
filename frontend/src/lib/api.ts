export class ApiError extends Error {
  status: number;
  issues: { code?: string; message: string; node_id?: string }[];
  code?: string;
  constructor(message: string, status: number, issues: ApiError["issues"] = [], code?: string) {
    super(message);
    this.status = status;
    this.issues = issues;
    this.code = code;
  }
}

let csrfToken = "";
let workspaceId = localStorage.getItem("ff_workspace") || "";
let onUnauthorized: (() => void) | null = null;

export const session = {
  setCsrf(token: string) {
    csrfToken = token;
  },
  setWorkspace(id: string) {
    workspaceId = id;
    localStorage.setItem("ff_workspace", id);
  },
  getWorkspace: () => workspaceId,
  onUnauthorized(fn: () => void) {
    onUnauthorized = fn;
  },
};

type Options = { method?: string; body?: unknown; params?: Record<string, string | number | boolean | undefined | null> };

export async function api<T = any>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method || "GET";
  const headers: Record<string, string> = {};
  if (csrfToken && method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let url = path;
  if (opts.params) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(opts.params)) {
      if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    }
    const text = query.toString();
    if (text) url += `?${text}`;
  }
  let response: Response;
  try {
    response = await fetch(url, { method, headers, credentials: "same-origin", body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  } catch {
    throw new ApiError("Could not reach the FlowForge server", 0);
  }
  const text = await response.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/auth/")) onUnauthorized?.();
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail?.message || `Request failed (${response.status})`;
    throw new ApiError(message, response.status, detail?.issues || data?.issues || [], detail?.code);
  }
  return data as T;
}
