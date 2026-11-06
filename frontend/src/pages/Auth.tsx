import { FlaskConical } from "lucide-react";
import { FormEvent, ReactNode, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Logo } from "../components/Layout";
import { Button, Field, Notice } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { User } from "../lib/types";

function Shell({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-base p-4" style={{ backgroundImage: "radial-gradient(#1a2638 1px, transparent 1px)", backgroundSize: "22px 22px" }}>
      <div className="w-full max-w-[400px]">
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <div className="card p-6 shadow-panel">
          <h1 className="text-lg font-semibold">{title}</h1>
          {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </div>
        {footer && <div className="mt-4 text-center text-[13px] text-muted">{footer}</div>}
      </div>
    </div>
  );
}

function useSubmit() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, run };
}

export function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { error, busy, run } = useSubmit();
  const after = (location.state as { from?: string } | null)?.from || "/";
  const [demoBusy, setDemoBusy] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      signIn(await api<User>("/api/auth/login", { method: "POST", body: { email, password } }));
      navigate(after, { replace: true });
    });
  };

  return (
    <Shell
      title="Sign in"
      subtitle="Build, run and monitor automated workflows."
      footer={
        <>
          New here?{" "}
          <Link className="text-primary-hover hover:underline" to="/register">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-3.5">
        {error && <Notice tone="warning">{error}</Notice>}
        <Field label="Email" htmlFor="email">
          <input id="email" type="email" autoComplete="email" required className="field" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password">
          <input id="password" type="password" autoComplete="current-password" required className="field" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <div className="text-right">
          <Link className="text-xs text-primary-hover hover:underline" to="/forgot-password">
            Forgot password?
          </Link>
        </div>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>
          Sign in
        </Button>
      </form>
      <div className="my-4 flex items-center gap-3 text-2xs text-faint">
        <div className="h-px flex-1 bg-line" /> OR <div className="h-px flex-1 bg-line" />
      </div>
      <Button
        className="w-full"
        loading={demoBusy}
        icon={<FlaskConical size={14} />}
        onClick={async () => {
          setDemoBusy(true);
          try {
            signIn(await api<User>("/api/auth/demo", { method: "POST" }));
            navigate("/", { replace: true });
          } catch (exc) {
            run(async () => {
              throw exc;
            });
          } finally {
            setDemoBusy(false);
          }
        }}
      >
        Explore the demo workspace
      </Button>
      <p className="mt-2 text-center text-2xs text-faint">Shared workspace with labelled example data. No account needed.</p>
    </Shell>
  );
}

export function Register() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "", workspace_name: "" });
  const { error, busy, run } = useSubmit();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });
  return (
    <Shell
      title="Create your account"
      footer={
        <>
          Already registered?{" "}
          <Link className="text-primary-hover hover:underline" to="/login">
            Sign in
          </Link>
        </>
      }
    >
      <form
        className="space-y-3.5"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            signIn(await api<User>("/api/auth/register", { method: "POST", body: form }));
            navigate("/", { replace: true });
          });
        }}
      >
        {error && <Notice tone="warning">{error}</Notice>}
        <Field label="Your name" htmlFor="name">
          <input id="name" required autoComplete="name" maxLength={120} className="field" value={form.name} onChange={set("name")} />
        </Field>
        <Field label="Email" htmlFor="email">
          <input id="email" type="email" required autoComplete="email" className="field" value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Password" htmlFor="password" hint="At least 10 characters.">
          <input id="password" type="password" required minLength={10} autoComplete="new-password" className="field" value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Workspace name (optional)" htmlFor="workspace">
          <input id="workspace" maxLength={120} className="field" placeholder="Acme Operations" value={form.workspace_name} onChange={set("workspace_name")} />
        </Field>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>
          Create account
        </Button>
      </form>
    </Shell>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<{ message: string; dev_reset_token?: string } | null>(null);
  const { error, busy, run } = useSubmit();
  return (
    <Shell title="Reset your password" footer={<Link className="text-primary-hover hover:underline" to="/login">Back to sign in</Link>}>
      {result ? (
        <div className="space-y-3">
          <Notice>{result.message}</Notice>
          {result.dev_reset_token && (
            <Notice tone="demo">
              <div className="font-medium">Development mode</div>
              <p className="text-xs">No mail provider is connected, so the link is shown here instead of being emailed. Production never shows it.</p>
              <Link className="mt-1 inline-block underline" to={`/reset-password?token=${encodeURIComponent(result.dev_reset_token)}`}>
                Continue to reset
              </Link>
            </Notice>
          )}
        </div>
      ) : (
        <form
          className="space-y-3.5"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => setResult(await api("/api/auth/password-reset/request", { method: "POST", body: { email } })));
          }}
        >
          {error && <Notice tone="warning">{error}</Notice>}
          <Field label="Email" htmlFor="email">
            <input id="email" type="email" required className="field" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" className="w-full" loading={busy}>
            Issue reset link
          </Button>
        </form>
      )}
    </Shell>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const { error, busy, run } = useSubmit();
  return (
    <Shell title="Choose a new password">
      <form
        className="space-y-3.5"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await api("/api/auth/password-reset/confirm", { method: "POST", body: { token: params.get("token") || "", new_password: password } });
            navigate("/login", { replace: true });
          });
        }}
      >
        {error && <Notice tone="warning">{error}</Notice>}
        <Field label="New password" htmlFor="password" hint="At least 10 characters.">
          <input id="password" type="password" required minLength={10} autoComplete="new-password" className="field" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>
          Update password
        </Button>
      </form>
    </Shell>
  );
}
