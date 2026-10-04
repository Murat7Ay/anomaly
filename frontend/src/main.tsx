import { CssBaseline, ThemeProvider } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { InboxPage } from "./pages/InboxPage";
import { IncidentPage } from "./pages/IncidentPage";
import { InsightsPage } from "./pages/InsightsPage";
import { InstitutionPage } from "./pages/InstitutionPage";
import { InstitutionsPage } from "./pages/InstitutionsPage";
import { LoginPage } from "./pages/LoginPage";
import { makeTheme } from "./theme";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 15_000 } },
});

function readMode(): "light" | "dark" {
  try {
    const v = localStorage.getItem("lg.mode");
    if (v === "light" || v === "dark") return v;
  } catch {
    /* ignore */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

function App() {
  const [mode, setMode] = useState<"light" | "dark">(readMode);
  const theme = useMemo(() => makeTheme(mode), [mode]);
  const toggle = () =>
    setMode((m) => {
      const next = m === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("lg.mode", next);
      } catch {
        /* ignore */
      }
      return next;
    });
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <RequireAuth>
                    <Layout mode={mode} toggleMode={toggle} />
                  </RequireAuth>
                }
              >
                <Route index element={<InboxPage />} />
                <Route path="incidents/:id" element={<IncidentPage />} />
                <Route path="institutions" element={<InstitutionsPage />} />
                <Route path="institutions/:id" element={<InstitutionPage />} />
                <Route path="approvals" element={<ApprovalsPage />} />
                <Route path="insights" element={<InsightsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
