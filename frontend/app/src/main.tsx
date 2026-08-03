import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { initAppearance } from "./lib/appearance";
import { registerServiceWorker } from "./lib/pwa";
import { createRoot } from "react-dom/client";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { IllustrationStyleGate } from "./components/IllustrationStyleGate";
import { BrowserRouter } from "react-router-dom";

import "./styles/typography.css";
import "./styles/tokens.css";
import "./styles/appearance.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/app.css";
import "./styles/auth.css";
import "./styles/ui.css";
import "./styles/shell.css";
import "./styles/dashboard.css";
import "./styles/cashflow-calendar.css";
import "./styles/coach.css";
import "./styles/investments.css";
import "./styles/debt.css";
import "./styles/accounts.css";
import "./styles/transactions.css";
import "./styles/budgets.css";
import "./styles/goals.css";
import "./styles/billing.css";
import "./styles/analytics.css";
import "./styles/insights.css";
import "./styles/settings.css";
import "./styles/responsive.css";
import "./styles/polish.css";
import "./styles/premium.css";
import "./styles/camera.css";
import "./styles/illustration.css";
import "./styles/landing.css";
import "./styles/admin.css";

import App from "./App";
import { ApiError } from "./api/client";
import { AuthProvider } from "./lib/AuthContext";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Financial data is worth a short staleness window rather than
      // refetching on every focus — but never silently retries a 401
      // (the client's own refresh logic already handles that once).
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return false;
        return failureCount < 2;
      },
    },
    mutations: {
      retry: false,
    },
  },
});

initAppearance();
registerServiceWorker();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Outermost, so a failure in the router, a provider or the shell itself
        shows a page instead of a blank tab. */}
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <IllustrationStyleGate>
          <BrowserRouter>
            <AuthProvider>
              <App />
            </AuthProvider>
          </BrowserRouter>
        </IllustrationStyleGate>
      </QueryClientProvider>
    </AppErrorBoundary>
  </StrictMode>,
);
