import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/AuthContext";

interface Props {
  children: ReactNode;
  /** Pages that themselves manage workspace selection (the picker) opt out. */
  requireWorkspace?: boolean;
  /**
   * What an unauthenticated visitor sees instead of being sent to the login
   * form. Only the root uses it, and only so that `/` can be the product's
   * front door for a stranger while remaining the dashboard for a customer —
   * without the dashboard's URL changing or every other route being touched.
   */
  publicFallback?: ReactNode;
}

export function ProtectedRoute({
  children,
  requireWorkspace = true,
  publicFallback,
}: Props) {
  const { isAuthenticated, activeWorkspace, workspaces, user } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    if (publicFallback) return <>{publicFallback}</>;
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // An operator account cannot own or join a workspace, so every customer
  // route is a dead end for it — the workspace picker would offer "create one"
  // and the API would refuse. Send them where their account actually works.
  // This is convenience; the service layer is the control.
  if (user?.is_platform_staff && !location.pathname.startsWith("/admin")) {
    return <Navigate to="/admin" replace />;
  }

  if (requireWorkspace && !activeWorkspace) {
    // Authenticated but no workspace selected/available yet — send them to
    // pick or create one rather than rendering a shell with nothing to show.
    if (workspaces.length === 0 || !activeWorkspace) {
      return <Navigate to="/workspaces" replace />;
    }
  }

  return <>{children}</>;
}
