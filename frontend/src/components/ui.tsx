import {
  AlertCircle,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  Clock,
  FlaskConical,
  Hourglass,
  Info,
  Loader2,
  MinusCircle,
  X,
  XCircle,
} from "lucide-react";
import {
  ButtonHTMLAttributes,
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { pretty } from "../lib/format";
import type { ExecStatus } from "../lib/types";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- buttons
type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-white hover:bg-primary-hover border-transparent",
  secondary: "bg-raised text-ink border-line hover:border-lineStrong hover:bg-[#1b2a40]",
  ghost: "bg-transparent text-muted border-transparent hover:bg-raised hover:text-ink",
  danger: "bg-danger/90 text-white border-transparent hover:bg-danger",
  success: "bg-success/15 text-success border-success/30 hover:bg-success/25",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  icon,
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "icon"; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || loading}
      className={cx(
        "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" && "h-7 px-2 text-xs",
        size === "md" && "h-8 px-3 text-[13px]",
        size === "icon" && "h-8 w-8",
        VARIANTS[variant],
        className,
      )}
    >
      {loading ? <Loader2 size={14} className="animate-spin" /> : icon}
      {children}
    </button>
  );
}

// --------------------------------------------------------------- tooltip
export function Tip({ text, children, side = "bottom" }: { text: string; children: ReactNode; side?: "bottom" | "top" | "right" }) {
  return (
    <span className="group/tip relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={cx(
          "pointer-events-none absolute z-50 hidden whitespace-nowrap rounded border border-line bg-[#0e1726] px-2 py-1 text-2xs font-medium text-ink shadow-panel group-hover/tip:block group-focus-within/tip:block",
          side === "bottom" && "left-1/2 top-full mt-1.5 -translate-x-1/2",
          side === "top" && "bottom-full left-1/2 mb-1.5 -translate-x-1/2",
          side === "right" && "left-full top-1/2 ml-2 -translate-y-1/2",
        )}
      >
        {text}
      </span>
    </span>
  );
}

// ----------------------------------------------------------------- badges
const TONE: Record<string, string> = {
  neutral: "bg-raised text-muted border-line",
  primary: "bg-primary-soft text-[#A5A7F8] border-primary/30",
  ai: "bg-ai-soft text-[#B9A0FA] border-ai/30",
  cyan: "bg-cyan-soft text-cyan border-cyan/25",
  success: "bg-success-soft text-[#4ADE80] border-success/30",
  warning: "bg-warning-soft text-[#FBBF24] border-warning/30",
  danger: "bg-danger-soft text-[#F87171] border-danger/30",
};

export function Badge({ tone = "neutral", icon, children, title }: { tone?: keyof typeof TONE | string; icon?: ReactNode; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-2xs font-medium", TONE[tone])}>
      {icon}
      {children}
    </span>
  );
}

const STATUS: Record<ExecStatus, { tone: string; label: string; icon: ReactNode }> = {
  pending: { tone: "neutral", label: "Pending", icon: <Clock size={12} /> },
  running: { tone: "primary", label: "Running", icon: <Loader2 size={12} className="animate-spin" /> },
  waiting: { tone: "cyan", label: "Waiting", icon: <Hourglass size={12} /> },
  completed: { tone: "success", label: "Completed", icon: <CheckCircle2 size={12} /> },
  failed: { tone: "danger", label: "Failed", icon: <XCircle size={12} /> },
  cancelled: { tone: "warning", label: "Cancelled", icon: <Ban size={12} /> },
  skipped: { tone: "neutral", label: "Skipped", icon: <MinusCircle size={12} /> },
};

export function StatusBadge({ status }: { status: ExecStatus }) {
  const s = STATUS[status] || STATUS.pending;
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.label}
    </Badge>
  );
}

export const DemoBadge = ({ label = "Demo data" }: { label?: string }) => (
  <Badge tone="cyan" icon={<FlaskConical size={11} />} title="Generated demonstration content, not a real execution or a real AI result">
    {label}
  </Badge>
);

export const SimulatedBadge = () => (
  <Badge tone="cyan" icon={<FlaskConical size={11} />} title="This step did not contact the outside world">
    Simulated
  </Badge>
);

// ------------------------------------------------------------------ states
export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded bg-raised", className)} />;
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-3" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 text-faint">{icon || <CircleDashed size={28} />}</div>
      <div className="text-sm font-semibold text-ink">{title}</div>
      {children && <div className="mt-1 max-w-md text-[13px] text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="m-3 flex items-center gap-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 text-[13px] text-[#FCA5A5]" role="alert">
      <AlertCircle size={16} className="shrink-0" />
      <span className="flex-1">{message}</span>
      {retry && (
        <Button size="sm" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warning" | "demo"; children: ReactNode }) {
  const styles = { info: "border-primary/30 bg-primary-soft text-[#C7C8FB]", warning: "border-warning/30 bg-warning-soft text-[#FCD34D]", demo: "border-cyan/25 bg-cyan-soft text-[#A5F3FC]" }[tone];
  const icon = { info: <Info size={15} />, warning: <AlertCircle size={15} />, demo: <FlaskConical size={15} /> }[tone];
  return (
    <div className={cx("flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]", styles)}>
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

// -------------------------------------------------------------- pagination
export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-muted">
      <span className="tabular">{total === 0 ? "No results" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total.toLocaleString()}`}</span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => onChange(page - 1)} icon={<ChevronLeft size={14} />} />
        <span className="tabular px-1">
          {page} / {pages}
        </span>
        <Button size="sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => onChange(page + 1)} icon={<ChevronRight size={14} />} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- modal
export function Modal({ title, onClose, children, footer, width = "max-w-lg" }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" className={cx("flex max-h-[88vh] w-full flex-col rounded-lg border border-line bg-surface shadow-panel outline-none", width)}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="text-sm font-semibold">{title}</div>
          <button aria-label="Close" className="rounded p-1 text-muted hover:bg-raised hover:text-ink" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

type ConfirmOptions = { title: string; body?: ReactNode; confirm?: string; danger?: boolean };
type ToastItem = { id: number; tone: "success" | "error" | "info"; message: string };

const FeedbackContext = createContext<{
  toast: (message: string, tone?: ToastItem["tone"]) => void;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
}>(null as never);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [dialog, setDialog] = useState<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);
  const counter = useRef(0);

  const toast = useCallback((message: string, tone: ToastItem["tone"] = "success") => {
    const id = ++counter.current;
    setToasts((items) => [...items.slice(-3), { id, tone, message }]);
    setTimeout(() => setToasts((items) => items.filter((t) => t.id !== id)), tone === "error" ? 7000 : 3500);
  }, []);
  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>((resolve) => setDialog({ ...options, resolve })), []);
  const close = (ok: boolean) => {
    dialog?.resolve(ok);
    setDialog(null);
  };

  return (
    <FeedbackContext.Provider value={{ toast, confirm }}>
      {children}
      {dialog && (
        <Modal
          title={dialog.title}
          onClose={() => close(false)}
          footer={
            <>
              <Button onClick={() => close(false)}>Cancel</Button>
              <Button variant={dialog.danger ? "danger" : "primary"} onClick={() => close(true)}>
                {dialog.confirm || "Confirm"}
              </Button>
            </>
          }
        >
          <div className="text-[13px] text-muted">{dialog.body}</div>
        </Modal>
      )}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto flex items-start gap-2 rounded-md border border-line bg-[#0e1726] px-3 py-2.5 text-[13px] shadow-panel">
            {t.tone === "success" && <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-success" />}
            {t.tone === "error" && <XCircle size={15} className="mt-0.5 shrink-0 text-danger" />}
            {t.tone === "info" && <Info size={15} className="mt-0.5 shrink-0 text-primary" />}
            <span className="min-w-0 flex-1 break-words">{t.message}</span>
          </div>
        ))}
      </div>
    </FeedbackContext.Provider>
  );
}

export const useFeedback = () => useContext(FeedbackContext);

// ---------------------------------------------------------------- misc
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 max-w-3xl text-[13px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function JsonView({ value, maxHeight = "max-h-72" }: { value: unknown; maxHeight?: string }) {
  if (value === undefined || value === null) return <div className="rounded-md border border-line bg-base/60 px-3 py-2 text-xs text-faint">No data</div>;
  return <pre className={cx("overflow-auto rounded-md border border-line bg-base/60 p-2.5 font-mono text-[11.5px] leading-relaxed text-[#CBD5E1]", maxHeight)}>{pretty(value)}</pre>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div role="tablist" className="flex items-center gap-0.5 border-b border-line px-2">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx(
            "-mb-px whitespace-nowrap border-b-2 px-2.5 py-2 text-xs font-medium transition-colors",
            value === t.id ? "border-primary text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function SegmentedControl<T extends string>({ options, value, onChange, label }: { options: { value: T; label: string }[]; value: T; onChange: (value: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-line bg-base/60 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx("rounded px-2.5 py-1 text-xs font-medium transition-colors", value === o.value ? "bg-raised text-ink" : "text-muted hover:text-ink")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, htmlFor, children, hint, error }: { label: ReactNode; htmlFor?: string; children: ReactNode; hint?: string; error?: string }) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-2xs text-faint">{hint}</p>}
      {error && <p className="mt-1 text-2xs text-[#F87171]">{error}</p>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx("relative h-[18px] w-8 shrink-0 rounded-full border transition-colors disabled:opacity-50", checked ? "border-primary bg-primary" : "border-line bg-raised")}
    >
      <span className={cx("absolute top-[2px] h-3 w-3 rounded-full bg-white transition-all", checked ? "left-[15px]" : "left-[2px]")} />
    </button>
  );
}
