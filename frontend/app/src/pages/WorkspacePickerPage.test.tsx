import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createWorkspace = vi.fn();
vi.mock("../api/tenancy", () => ({
  tenancyApi: { createWorkspace: (...a: unknown[]) => createWorkspace(...a) },
}));

const switchWorkspace = vi.fn();
const refreshWorkspaces = vi.fn().mockResolvedValue(undefined);
let mockWorkspaces: { tenant: { id: string; name: string; base_currency: string }; role: string }[] = [];
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ workspaces: mockWorkspaces, switchWorkspace, refreshWorkspaces }),
}));

import { WorkspacePickerPage } from "./WorkspacePickerPage";

beforeEach(() => {
  vi.clearAllMocks();
  mockWorkspaces = [];
});

async function submit(user: ReturnType<typeof userEvent.setup>, type: string) {
  await user.type(screen.getByLabelText(/workspace name/i), "The Riveras");
  await user.selectOptions(screen.getByLabelText(/^type$/i), type);
  await user.click(screen.getByRole("button", { name: /create workspace/i }));
}

describe("WorkspacePickerPage — workspace type mapping", () => {
  it("sends 'personal' through unchanged", async () => {
    createWorkspace.mockResolvedValue({ tenant: { id: "t1" } });
    const user = userEvent.setup();
    render(<WorkspacePickerPage />);

    await submit(user, "personal");
    expect(createWorkspace).toHaveBeenCalledWith(
      expect.objectContaining({ type: "personal", country: "KE", base_currency: "KES" }),
    );
  });

  it("maps 'Couple' to the backend's actual 'household' type", async () => {
    // Regression: the backend's TenantType has no "couple" value at all —
    // submitting it directly used to hit a clean 400 from DRF's ChoiceField,
    // surfaced as a raw, unhelpful validation message. From the user's side,
    // picking "Couple" and submitting just failed.
    createWorkspace.mockResolvedValue({ tenant: { id: "t1" } });
    const user = userEvent.setup();
    render(<WorkspacePickerPage />);

    await submit(user, "couple");
    expect(createWorkspace).toHaveBeenCalledWith(expect.objectContaining({ type: "household" }));
  });

  it("maps 'Family' to the same backend 'household' type", async () => {
    createWorkspace.mockResolvedValue({ tenant: { id: "t1" } });
    const user = userEvent.setup();
    render(<WorkspacePickerPage />);

    await submit(user, "family");
    expect(createWorkspace).toHaveBeenCalledWith(expect.objectContaining({ type: "household" }));
  });

  it("still offers Couple and Family as distinct, selectable options", () => {
    // The mapping happens only at submission time — the picker itself must
    // keep both as genuinely separate options, not collapse them into one
    // <option> sharing a value, which would break native <select> selection.
    render(<WorkspacePickerPage />);
    const select = screen.getByLabelText(/^type$/i) as HTMLSelectElement;
    const labels = Array.from(select.options).map((o) => o.text);
    expect(labels).toEqual(["Personal", "Couple", "Family"]);
  });

  it("a successful creation switches to the new workspace", async () => {
    createWorkspace.mockResolvedValue({ tenant: { id: "new-workspace-id" } });
    const user = userEvent.setup();
    render(<WorkspacePickerPage />);

    await submit(user, "family");
    expect(switchWorkspace).toHaveBeenCalledWith("new-workspace-id");
  });
});

describe("WorkspacePickerPage — workspaces arriving after mount", () => {
  const ws = (id: string, name: string) => ({
    tenant: { id, name, base_currency: "USD" },
    role: "owner",
  });

  it("shows the chooser once workspaces load, having mounted with none", () => {
    // The session bootstraps asynchronously, so this page routinely renders
    // first with an empty list and receives the real one a tick later. Reading
    // that first empty render into useState latched the create form on
    // permanently: the account had six workspaces and still saw "Create your
    // first workspace", and creating a seventh never escaped it.
    const { rerender } = render(<WorkspacePickerPage />);
    expect(screen.getByRole("heading", { name: /create your first workspace/i })).toBeInTheDocument();

    mockWorkspaces = [ws("t1", "Personal")];
    rerender(<WorkspacePickerPage />);

    expect(screen.getByRole("heading", { name: /choose a workspace/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Personal/ })).toBeInTheDocument();
  });

  it("still opens the form when the chooser's own button asks for it", async () => {
    // The fix must not make the create form unreachable for someone who
    // already has workspaces and wants another.
    mockWorkspaces = [ws("t1", "Personal")];
    const user = userEvent.setup();
    render(<WorkspacePickerPage />);

    await user.click(screen.getByRole("button", { name: /new workspace/i }));
    expect(screen.getByRole("heading", { name: /new workspace/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/workspace name/i)).toBeInTheDocument();
  });

  it("keeps the form open across a re-render once it was explicitly opened", async () => {
    mockWorkspaces = [ws("t1", "Personal")];
    const user = userEvent.setup();
    const { rerender } = render(<WorkspacePickerPage />);
    await user.click(screen.getByRole("button", { name: /new workspace/i }));

    mockWorkspaces = [ws("t1", "Personal"), ws("t2", "Household")];
    rerender(<WorkspacePickerPage />);

    expect(screen.getByLabelText(/workspace name/i)).toBeInTheDocument();
  });
});
