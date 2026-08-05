import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { RetiredRoute } from "./components/RetiredRoute";
import { useFlag } from "./lib/featureFlags";
import { useAuth } from "./lib/AuthContext";

// Route-level code splitting: the heaviest deps (Recharts on the dashboard,
// the various forms) load only when their route is visited, keeping the
// initial login bundle small.
const DashboardPage = lazy(() => import("./pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const TransactionsPage = lazy(() => import("./pages/TransactionsPage").then((m) => ({ default: m.TransactionsPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const ReviewPage = lazy(() => import("./pages/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const HouseholdPage = lazy(() =>
  import("./pages/HouseholdPage").then((m) => ({ default: m.HouseholdPage })),
);
const ProjectionsPage = lazy(() =>
  import("./pages/ProjectionsPage").then((m) => ({ default: m.ProjectionsPage })),
);
const DebtPage = lazy(() => import("./pages/DebtPage").then((m) => ({ default: m.DebtPage })));
const InvestmentsPage = lazy(() => import("./pages/InvestmentsPage").then((m) => ({ default: m.InvestmentsPage })));
const IncomePage = lazy(() => import("./pages/IncomePage").then((m) => ({ default: m.IncomePage })));
const ReceivablesPage = lazy(() =>
  import("./pages/ReceivablesPage").then((m) => ({ default: m.ReceivablesPage })),
);
const CoachPage = lazy(() => import("./pages/CoachPage").then((m) => ({ default: m.CoachPage })));
const CashflowPage = lazy(() => import("./pages/CashflowPage").then((m) => ({ default: m.CashflowPage })));
const BudgetsPage = lazy(() => import("./pages/BudgetsPage").then((m) => ({ default: m.BudgetsPage })));
const GoalsPage = lazy(() => import("./pages/GoalsPage").then((m) => ({ default: m.GoalsPage })));
const BillsPage = lazy(() => import("./pages/BillsPage").then((m) => ({ default: m.BillsPage })));
const NotificationsPage = lazy(() => import("./pages/NotificationsPage").then((m) => ({ default: m.NotificationsPage })));
const LoginPage = lazy(() => import("./pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const RegisterPage = lazy(() => import("./pages/RegisterPage").then((m) => ({ default: m.RegisterPage })));
const ForgotPasswordPage = lazy(() =>
  import("./pages/ForgotPasswordPage").then((m) => ({ default: m.ForgotPasswordPage })),
);
const ResetPasswordPage = lazy(() =>
  import("./pages/ResetPasswordPage").then((m) => ({ default: m.ResetPasswordPage })),
);
const LoggedOutPage = lazy(() => import("./pages/LoggedOutPage").then((m) => ({ default: m.LoggedOutPage })));
const WorkspacePickerPage = lazy(() =>
  import("./pages/WorkspacePickerPage").then((m) => ({ default: m.WorkspacePickerPage })),
);
const AccountsPage = lazy(() => import("./pages/AccountsPage").then((m) => ({ default: m.AccountsPage })));
const CategoriesPage = lazy(() => import("./pages/CategoriesPage").then((m) => ({ default: m.CategoriesPage })));
const RecurringPage = lazy(() => import("./pages/RecurringPage").then((m) => ({ default: m.RecurringPage })));
const InsightsPage = lazy(() => import("./pages/InsightsPage").then((m) => ({ default: m.InsightsPage })));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })));
const ReceiptScanPage = lazy(() => import("./pages/ReceiptScanPage").then((m) => ({ default: m.ReceiptScanPage })));
const QuickAddPage = lazy(() => import("./pages/QuickAddPage").then((m) => ({ default: m.QuickAddPage })));
// Phase 5 IA. Both hubs are always routable so the new structure can be
// previewed without flipping the flag; only the *redirects* and the rail are
// gated, because those are what change habitual behaviour.
const NotFoundPage = lazy(() => import("./pages/StatusPage").then((m) => ({ default: m.NotFoundPage })));
const MaintenancePage = lazy(() => import("./pages/StatusPage").then((m) => ({ default: m.MaintenancePage })));
const OfflinePage = lazy(() => import("./pages/StatusPage").then((m) => ({ default: m.OfflinePage })));
const LandingPage = lazy(() => import("./pages/LandingPage").then((m) => ({ default: m.LandingPage })));
const PlanPage = lazy(() => import("./pages/PlanPage").then((m) => ({ default: m.PlanPage })));
const InsightsHubPage = lazy(() =>
  import("./pages/InsightsHubPage").then((m) => ({ default: m.InsightsHubPage })),
);
const AutomationPage = lazy(() => import("./pages/AutomationPage").then((m) => ({ default: m.AutomationPage })));
const MembersPage = lazy(() => import("./pages/MembersPage").then((m) => ({ default: m.MembersPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const BillingPage = lazy(() => import("./pages/BillingPage").then((m) => ({ default: m.BillingPage })));
const AcceptInvitePage = lazy(() => import("./pages/AcceptInvitePage").then((m) => ({ default: m.AcceptInvitePage })));
const OAuthCallbackPage = lazy(() => import("./pages/OAuthCallbackPage").then((m) => ({ default: m.OAuthCallbackPage })));
const ComponentShowcase = lazy(() => import("./pages/ComponentShowcase").then((m) => ({ default: m.ComponentShowcase })));

// Platform administration workspace. Lazily loaded as its own chunk so the
// customer bundle never carries it — the overwhelming majority of sessions are
// customers, and they should not download an admin console to see their
// budget.
const AdminShell = lazy(() => import("./components/admin/AdminShell").then((m) => ({ default: m.AdminShell })));
const AdminGuard = lazy(() => import("./components/admin/AdminShell").then((m) => ({ default: m.AdminGuard })));
const AdminDashboardPage = lazy(() =>
  import("./pages/admin/AdminDashboardPage").then((m) => ({ default: m.AdminDashboardPage })),
);
const AdminAnalyticsPage = lazy(() =>
  import("./pages/admin/AdminDashboardPage").then((m) => ({ default: m.AdminAnalyticsPage })),
);
const AdminTenantsPage = lazy(() =>
  import("./pages/admin/AdminTenantsPage").then((m) => ({ default: m.AdminTenantsPage })),
);
const AdminTenantDetailPage = lazy(() =>
  import("./pages/admin/AdminTenantsPage").then((m) => ({ default: m.AdminTenantDetailPage })),
);
const AdminBillingPage = lazy(() =>
  import("./pages/admin/AdminPages").then((m) => ({ default: m.AdminBillingPage })),
);
const AdminInvoicesPage = lazy(() =>
  import("./pages/admin/AdminPages").then((m) => ({ default: m.AdminInvoicesPage })),
);
const AdminDunningPage = lazy(() =>
  import("./pages/admin/AdminPages").then((m) => ({ default: m.AdminDunningPage })),
);
const AdminCouponsPage = lazy(() =>
  import("./pages/admin/AdminPages").then((m) => ({ default: m.AdminCouponsPage })),
);
const AdminPlansPage = lazy(() =>
  import("./pages/admin/AdminPlansPage").then((m) => ({ default: m.AdminPlansPage })),
);
const AdminHealthPage = lazy(() =>
  import("./pages/admin/AdminPages").then((m) => ({ default: m.AdminHealthPage })),
);
const AdminAuditPage = lazy(() =>
  import("./pages/admin/AdminPages").then((m) => ({ default: m.AdminAuditPage })),
);
const AdminStaffPage = lazy(() =>
  import("./pages/admin/AdminPages").then((m) => ({ default: m.AdminStaffPage })),
);
const AdminSettingsPage = lazy(() =>
  import("./pages/admin/AdminSettingsPage").then((m) => ({ default: m.AdminSettingsPage })),
);

/** `/insights` meant "anomalies" before Phase 5 and means the hub after it.
 * Same URL, two products — so the flag decides, not the router table. */
function InsightsRoute() {
  const [navV2] = useFlag("navV2");
  return navV2 ? <InsightsHubPage /> : <InsightsPage />;
}

export default function App() {
  const { isLoading } = useAuth();

  if (isLoading) {
    return <div className="lf-app-loading">Loading LedgerFlow…</div>;
  }

  return (
    <Suspense fallback={<div className="lf-app-loading">Loading…</div>}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/logged-out" element={<LoggedOutPage />} />
        <Route path="/auth/callback" element={<OAuthCallbackPage />} />

        {import.meta.env.DEV && <Route path="/_ui" element={<ComponentShowcase />} />}

        <Route
          path="/workspaces"
          element={
            <ProtectedRoute requireWorkspace={false}>
              <WorkspacePickerPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/invite"
          element={
            <ProtectedRoute requireWorkspace={false}>
              <AcceptInvitePage />
            </ProtectedRoute>
          }
        />

        {/* The root is the only route a stranger is allowed to reach, and it
            is the dashboard for everyone else. Declaring it as its own layout
            keeps the dashboard's URL exactly where it was and leaves every
            other protected route's behaviour untouched. */}
        <Route
          path="/"
          element={
            <ProtectedRoute publicFallback={<LandingPage />}>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route index element={<DashboardPage />} />
        </Route>

        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route path="/investments" element={<InvestmentsPage />} />
          <Route path="/income" element={<IncomePage />} />
          <Route path="/debt" element={<DebtPage />} />
          <Route path="/receivables" element={<ReceivablesPage />} />
          <Route path="/accounts" element={<AccountsPage />} />
          <Route path="/categories" element={<CategoriesPage />} />
          <Route path="/goals" element={<GoalsPage />} />

          {/* Phase 5 destinations. Always routable. */}
          <Route path="/activity" element={<TransactionsPage />} />
          <Route path="/plan" element={<PlanPage />} />

          {/* Retired paths: legacy page with the flag off, redirect with it on.
              A bookmark is a promise — none of these 404, ever. */}
          <Route path="/transactions" element={<RetiredRoute path="/transactions" legacy={<TransactionsPage />} />} />
          <Route path="/budgets" element={<RetiredRoute path="/budgets" legacy={<BudgetsPage />} />} />
          <Route path="/bills" element={<RetiredRoute path="/bills" legacy={<BillsPage />} />} />
          <Route path="/recurring" element={<RetiredRoute path="/recurring" legacy={<RecurringPage />} />} />
          <Route path="/cashflow" element={<RetiredRoute path="/cashflow" legacy={<CashflowPage />} />} />
          <Route path="/coach" element={<RetiredRoute path="/coach" legacy={<CoachPage />} />} />
          <Route path="/analytics" element={<RetiredRoute path="/analytics" legacy={<AnalyticsPage />} />} />
          <Route path="/reports" element={<RetiredRoute path="/reports" legacy={<ReportsPage />} />} />

          {/* `/insights` is the one contested name: it was the anomalies page,
              and the new IA gives it to the hub that made anomalies a tab. */}
          <Route path="/insights" element={<InsightsRoute />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/projections" element={<ProjectionsPage />} />
          <Route path="/household" element={<HouseholdPage />} />
          <Route path="/automation" element={<AutomationPage />} />
          <Route path="/quick-add" element={<QuickAddPage />} />
          <Route path="/receipts/scan" element={<ReceiptScanPage />} />
          <Route path="/members" element={<MembersPage />} />
          <Route path="/settings/*" element={<SettingsPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
        </Route>

        {/* Platform workspace. Sits outside the tenant AppShell entirely — it
            has no workspace context, and ProtectedRoute's requireWorkspace
            would bounce an operator who belongs to no household. */}
        <Route
          path="/admin"
          element={
            <ProtectedRoute requireWorkspace={false}>
              <AdminGuard>
                <AdminShell />
              </AdminGuard>
            </ProtectedRoute>
          }
        >
          <Route index element={<AdminDashboardPage />} />
          <Route path="tenants" element={<AdminTenantsPage />} />
          <Route path="tenants/:tenantId" element={<AdminTenantDetailPage />} />
          <Route path="billing" element={<AdminBillingPage />} />
          <Route path="invoices" element={<AdminInvoicesPage />} />
          <Route path="dunning" element={<AdminDunningPage />} />
          <Route path="coupons" element={<AdminCouponsPage />} />
          <Route path="plans" element={<AdminPlansPage />} />
          <Route path="analytics" element={<AdminAnalyticsPage />} />
          <Route path="health" element={<AdminHealthPage />} />
          <Route path="audit" element={<AdminAuditPage />} />
          <Route path="staff" element={<AdminStaffPage />} />
          <Route path="settings" element={<AdminSettingsPage />} />
        </Route>

        {/* Public utility states. `/offline` and `/maintenance` are addressable
            so an operator or a service worker can send someone to them. */}
        <Route path="/maintenance" element={<MaintenancePage />} />
        <Route path="/offline" element={<OfflinePage />} />

        {/* A wrong URL used to redirect silently to the overview, which tells
            the user their link was fine and they simply ended up elsewhere. */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  );
}
