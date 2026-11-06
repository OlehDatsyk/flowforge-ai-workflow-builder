export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  const minutes = Math.floor(ms / 60_000);
  return `${minutes}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function timeAgo(value: string | null | undefined, now = Date.now()): string {
  if (!value) return "Never";
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 30 * 86_400) return `${Math.floor(seconds / 86_400)}d ago`;
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 11)}...` : id;
}

export function number(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString();
}

export function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return String(value);
  }
}

export const ERROR_TYPE_LABEL: Record<string, string> = {
  network: "Network",
  timeout: "Timeout",
  http_status: "HTTP error status",
  validation: "Invalid data",
  config: "Configuration",
  expression: "Expression",
  security: "Blocked by security policy",
  ai: "AI provider",
  auth: "Authentication",
  resource_limit: "Resource limit",
  worker_interrupted: "Worker interrupted",
  internal: "Internal error",
  execution: "Execution",
  unknown: "Unknown",
};
