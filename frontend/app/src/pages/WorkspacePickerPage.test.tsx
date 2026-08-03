import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createWorkspace = vi.fn();
vi.mock("../api/tenancy", () => ({
  tenancyApi: { createWorkspace: (...a: unknown[]) => createWorkspace(...a) },
}));

const switchWorkspace = vi.fn();
const refreshWorkspaces = vi.fn().mockResolvedValue(undefined);
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ workspaces: [], switchWorkspace, refreshWorkspaces }),
}));

import { WorkspacePickerPage } from "./WorkspacePickerPage";

beforeEach(() => vi.clearAllMocks());

async function submit(user: ReturnType<typeof userEvent.setup>, type: string) {
  await user.type(screen.getByLabelText(/workspace name/i), "The Riveras");
  await user.selectOptions(screen.getByLabelText(/^type$/i), type);
  const currency = screen.getByLabelText(/base currency/i) as HTMLInputElement;
  await user.clear(currency);
  await user.type(currency, "USD");
  await user.click(screen.getByRole("button", { name: /create workspace/i }));
}

describe("WorkspacePickerPage — workspace type mapping", () => {
  it("sends 'personal' through unchanged", async () => {
    createWorkspace.mockResolvedValue({ tenant: { id: "t1" } });
    const user = userEvent.setup();
    render(<WorkspacePickerPage />);

    await submit(user, "personal");
    expect(createWorkspace).toHaveBeenCalledWith(expect.objectContaining({ type: "personal" }));
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
