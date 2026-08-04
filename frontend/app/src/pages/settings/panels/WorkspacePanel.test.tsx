import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tenancyApi } from "../../../api/tenancy";
import { WorkspacePanel } from "./WorkspacePanel";

vi.mock("../../../api/tenancy", () => ({
  tenancyApi: {
    exportWorkspace: vi.fn(),
    closeWorkspace: vi.fn(),
    updateWorkspace: vi.fn(),
  },
}));

const workspace = {
  id: "w1",
  role: "owner",
  created_at: "2026-01-01",
  tenant: { id: "t1", name: "Rivera Household", type: "family", base_currency: "USD", default_locale: "en-US", default_timezone: "UTC" },
};
const ws = (id: string, name: string, role = "owner") => ({
  id: `w-${id}`,
  role,
  created_at: "2026-01-01",
  tenant: {
    id,
    name,
    type: "personal",
    base_currency: "USD",
    default_locale: "en-US",
    default_timezone: "UTC",
  },
});

let mockWorkspaces: ReturnType<typeof ws>[] = [];
const refreshWorkspaces = vi.fn().mockResolvedValue(undefined);
const switchWorkspace = vi.fn();
vi.mock("../../../lib/AuthContext", () => ({
  useAuth: () => ({
    activeWorkspace: workspace,
    workspaces: mockWorkspaces,
    refreshWorkspaces,
    switchWorkspace,
  }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockWorkspaces = [];
});

function renderPanel() {
  return render(
    <MemoryRouter>
      <WorkspacePanel />
    </MemoryRouter>,
  );
}

describe("WorkspacePanel data & privacy", () => {
  it("exports the workspace data as a download", async () => {
    vi.mocked(tenancyApi.exportWorkspace).mockResolvedValue({ workspace: { id: "t1" } });
    // jsdom lacks URL.createObjectURL / anchor click side effects; stub them.
    const createURL = vi.fn(() => "blob:x");
    const revokeURL = vi.fn();
    Object.assign(URL, { createObjectURL: createURL, revokeObjectURL: revokeURL });

    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(tenancyApi.exportWorkspace).toHaveBeenCalledWith("t1"));
  });

  it("guards closure behind typing the exact workspace name", () => {
    renderPanel();
    // Reveal the advanced closure disclosure.
    fireEvent.click(screen.getByRole("button", { name: /close this workspace/i }));

    const closeBtn = screen.getByRole("button", { name: "Close workspace" });
    expect(closeBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Confirm"), { target: { value: "wrong" } });
    expect(closeBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Confirm"), { target: { value: "Rivera Household" } });
    expect(closeBtn).toBeEnabled();
  });
});

describe("WorkspacePanel — managing every workspace", () => {
  const many = () => [
    ws("t1", "Rivera Household"),
    ws("t2", "Personal"),
    ws("t3", "Personal"),
  ];

  it("stays hidden when there is only one workspace to manage", () => {
    // A list of one is noise: everything above already describes it.
    mockWorkspaces = [ws("t1", "Rivera Household")];
    renderPanel();
    expect(screen.queryByText("All your workspaces")).not.toBeInTheDocument();
  });

  it("lists every workspace once there is more than one", () => {
    mockWorkspaces = many();
    renderPanel();
    expect(screen.getByText("All your workspaces")).toBeInTheDocument();
    expect(screen.getAllByText("Personal")).toHaveLength(2);
  });

  it("closes a workspace you are not currently in", async () => {
    // The gap this section fills: tidying a duplicate previously meant
    // switching into it first, because the panel only ever described the
    // active one.
    mockWorkspaces = many();
    vi.mocked(tenancyApi.closeWorkspace).mockResolvedValue(undefined as never);
    renderPanel();

    fireEvent.click(screen.getAllByRole("button", { name: /^close$/i })[1]);
    fireEvent.change(screen.getByLabelText(/confirm/i), { target: { value: "Personal" } });
    fireEvent.click(screen.getByRole("button", { name: /close workspace/i }));

    await waitFor(() => expect(tenancyApi.closeWorkspace).toHaveBeenCalledWith("t2"));
  });

  it("will not close until the name is typed exactly", () => {
    mockWorkspaces = many();
    renderPanel();

    fireEvent.click(screen.getAllByRole("button", { name: /^close$/i })[1]);
    fireEvent.change(screen.getByLabelText(/confirm/i), { target: { value: "person" } });

    expect(screen.getByRole("button", { name: /close workspace/i })).toBeDisabled();
  });

  it("renames a workspace", async () => {
    mockWorkspaces = many();
    vi.mocked(tenancyApi.updateWorkspace).mockResolvedValue({} as never);
    renderPanel();

    fireEvent.click(screen.getAllByRole("button", { name: /rename/i })[1]);
    fireEvent.change(screen.getByLabelText(/new name/i), { target: { value: "Holiday fund" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(tenancyApi.updateWorkspace).toHaveBeenCalledWith("t2", { name: "Holiday fund" }),
    );
  });

  it("offers no rename or close on a workspace you only belong to", () => {
    // The API refuses a PATCH or DELETE from a non-owner, and a button that
    // only ever 403s is worse than no button.
    mockWorkspaces = [ws("t1", "Rivera Household"), ws("t2", "Shared", "member")];
    renderPanel();

    // One each, for the owned workspace only.
    expect(screen.getAllByRole("button", { name: /rename/i })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /^close$/i })).toHaveLength(1);
  });
});
