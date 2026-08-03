import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tenancyApi } from "../../../api/tenancy";
import { WorkspacePanel } from "./WorkspacePanel";

vi.mock("../../../api/tenancy", () => ({
  tenancyApi: { exportWorkspace: vi.fn(), closeWorkspace: vi.fn() },
}));

const workspace = {
  id: "w1",
  role: "owner",
  created_at: "2026-01-01",
  tenant: { id: "t1", name: "Rivera Household", type: "family", base_currency: "USD", default_locale: "en-US", default_timezone: "UTC" },
};
vi.mock("../../../lib/AuthContext", () => ({ useAuth: () => ({ activeWorkspace: workspace }) }));

beforeEach(() => vi.clearAllMocks());

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
