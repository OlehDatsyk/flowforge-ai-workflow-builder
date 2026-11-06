import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import { StrictMode, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppLayout } from "./components/Layout";
import { FeedbackProvider, Skeleton } from "./components/ui";
import "./index.css";
import { AuthProvider, CatalogueProvider, useAuth } from "./lib/auth";
import { ForgotPassword, Login, Register, ResetPassword } from "./pages/Auth";

const Overview = lazy(() => import("./pages/Overview"));
const Workflows = lazy(() => import("./pages/Workflows"));
const Editor = lazy(() => import("./editor/Editor"));
const Templates = lazy(() => import("./pages/Templates"));
const AIBuilder = lazy(() => import("./pages/AIBuilder"));
const Integrations = lazy(() => import("./pages/Integrations"));
const Executions = lazy(() => import("./pages/Executions"));
const ExecutionDetail = lazy(() => import("./pages/ExecutionDetail"));
const ExecutionCompare = lazy(() => import("./pages/ExecutionCompare"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Credentials = lazy(() => import("./pages/Credentials"));
const Settings = lazy(() => import("./pages/Settings"));

function Protected() {
  const { user, loading, workspaceId } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center" aria-label="Loading">
        <Skeleton className="h-8 w-40" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return (
    <CatalogueProvider key={workspaceId}>
      <AppLayout />
    </CatalogueProvider>
  );
}

function PublicOnly({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Navigate to="/" replace /> : children;
}

const fallback = (
  <div className="p-6" aria-label="Loading page">
    <Skeleton className="mb-4 h-7 w-56" />
    <Skeleton className="h-64 w-full" />
  </div>
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <FeedbackProvider>
          <Suspense fallback={fallback}>
            <Routes>
              <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
              <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route element={<Protected />}>
                <Route index element={<Overview />} />
                <Route path="workflows" element={<Workflows />} />
                <Route path="workflows/:id" element={<Editor />} />
                <Route path="templates" element={<Templates />} />
                <Route path="ai" element={<AIBuilder />} />
                <Route path="integrations" element={<Integrations />} />
                <Route path="executions" element={<Executions />} />
                <Route path="executions/compare" element={<ExecutionCompare />} />
                <Route path="executions/:id" element={<ExecutionDetail />} />
                <Route path="analytics" element={<Analytics />} />
                <Route path="credentials" element={<Credentials />} />
                <Route path="settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </Suspense>
        </FeedbackProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
