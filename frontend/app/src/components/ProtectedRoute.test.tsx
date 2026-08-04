import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

type AuthState = {
  isAuthenticated: boolean;
  isLoading: boolean;
  activeWorkspace: unknown;
  workspaces: unknown[];
  user: { is_platform_staff?: boolean } | null;
};

let auth: AuthState;
vi.mock("../lib/AuthContext", () => ({ useAuth: () => auth }));

import { ProtectedRoute } from "./ProtectedRoute";

beforeEach(() => {
  auth = {
    isAuthenticated: false,
    isLoading: false,
    activeWorkspace: null,
    workspaces: [],
    user: null,
  };
});

function renderAt(path: string, element: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path} element={element} />
        <Route path="/login" element={<div>login page</div>} />
        <Route path="/workspaces" element={<div>workspace picker</div>} />
        <Route path="/admin" element={<div>admin console</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  it("decides nothing while the session is still bootstrapping", () => {
    // Every field is empty during bootstrap, which is indistinguishable from
    // "signed out with no workspaces" unless isLoading is consulted. Acting on
    // it fires a `replace` navigation to /login that cannot be undone once the
    // real session arrives a tick later.
    auth.isLoading = true;

    renderAt("/dashboard", <ProtectedRoute>dashboard</ProtectedRoute>);

    expect(screen.queryByText("login page")).not.toBeInTheDocument();
    expect(screen.queryByText("workspace picker")).not.toBeInTheDocument();
    expect(screen.queryByText("dashboard")).not.toBeInTheDocument();
  });

  it("does not strand a signed-in user at the picker while workspaces load", () => {
    auth.isLoading = true;
    auth.isAuthenticated = true;

    renderAt("/dashboard", <ProtectedRoute>dashboard</ProtectedRoute>);

    expect(screen.queryByText("workspace picker")).not.toBeInTheDocument();
  });

  it("sends a genuinely signed-out visitor to the login form", () => {
    renderAt("/dashboard", <ProtectedRoute>dashboard</ProtectedRoute>);
    expect(screen.getByText("login page")).toBeInTheDocument();
  });

  it("renders the page once a session and workspace are both resolved", () => {
    auth.isAuthenticated = true;
    auth.activeWorkspace = { tenant: { id: "t1" } };
    auth.workspaces = [auth.activeWorkspace];

    renderAt("/dashboard", <ProtectedRoute>dashboard</ProtectedRoute>);
    expect(screen.getByText("dashboard")).toBeInTheDocument();
  });

  it("sends a signed-in user with no workspace to the picker", () => {
    auth.isAuthenticated = true;

    renderAt("/dashboard", <ProtectedRoute>dashboard</ProtectedRoute>);
    expect(screen.getByText("workspace picker")).toBeInTheDocument();
  });
});

describe("ProtectedRoute — platform staff who also use the product", () => {
  it("sends a staff account with no workspaces to the console", () => {
    auth.isAuthenticated = true;
    auth.user = { is_platform_staff: true };

    renderAt("/dashboard", <ProtectedRoute>dashboard</ProtectedRoute>);
    expect(screen.getByText("admin console")).toBeInTheDocument();
  });

  it("lets a staff account that has workspaces use them", () => {
    // Holding a membership is only possible when the deployment turned
    // PLATFORM_STAFF_SEPARATE_FROM_TENANTS off, which is a deliberate choice
    // the UI must not override — a solo operator dogfooding their own install
    // was otherwise bounced to /admin from every customer route.
    auth.isAuthenticated = true;
    auth.user = { is_platform_staff: true };
    auth.activeWorkspace = { tenant: { id: "t1" } };
    auth.workspaces = [auth.activeWorkspace];

    renderAt("/dashboard", <ProtectedRoute>dashboard</ProtectedRoute>);
    expect(screen.getByText("dashboard")).toBeInTheDocument();
  });
});
