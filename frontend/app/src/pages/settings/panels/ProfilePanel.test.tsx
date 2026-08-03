import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const update = vi.fn();
vi.mock("../../../api/auth", () => ({ profileApi: { update: (...a: unknown[]) => update(...a) } }));
vi.mock("../../../lib/AuthContext", () => ({
  useAuth: () => ({ user: { email: "amina@example.test", first_name: "Amina", last_name: "Otieno" } }),
}));

import { ProfilePanel } from "./ProfilePanel";

/** Real timers, real 800ms debounce.
 *
 * Fake timers deadlock here: `userEvent` and testing-library's `waitFor` each
 * drive their own scheduling, and with `vi.useFakeTimers()` every interaction
 * hung to the 5s test timeout. Waiting out the actual debounce costs about a
 * second per case and tests the behaviour that ships rather than a stand-in
 * for it. Hence the explicit `waitFor` timeouts — the default 1000ms leaves no
 * margin over a 800ms debounce. */
const SETTLE = { timeout: 3000 };

function setup() {
  const user = userEvent.setup();
  render(<ProfilePanel />);
  return user;
}

beforeEach(() => {
  update.mockReset();
  update.mockResolvedValue({});
});

describe("ProfilePanel autosave", () => {
  it("saves nothing on mount", async () => {
    setup();
    await new Promise((r) => setTimeout(r, 1200));
    // The commonest autosave bug: treating the initial render as a change and
    // writing the values back over themselves.
    expect(update).not.toHaveBeenCalled();
  });

  it("waits for a pause rather than saving per keystroke", async () => {
    const user = setup();
    await user.type(screen.getByLabelText("First name"), "!!!");
    expect(update).not.toHaveBeenCalled();

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1), SETTLE);
    expect(update).toHaveBeenCalledWith({ first_name: "Amina!!!", last_name: "Otieno" });
  });

  it("confirms the save, because autosave without confirmation is worse than a button", async () => {
    const user = setup();
    await user.type(screen.getByLabelText("Last name"), "!");
    await waitFor(() => expect(screen.getByText(/all changes saved/i)).toBeInTheDocument(), SETTLE);
  });

  it("commits immediately when a field is left", async () => {
    // Tabbing away and navigating inside the debounce window would otherwise
    // discard the edit silently — the failure that makes people distrust
    // autosave.
    const user = setup();
    await user.type(screen.getByLabelText("First name"), "!");
    await user.tab();
    // No debounce wait: blur commits at once.
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 400 });
  });

  it("stops saving once the value matches what the server holds", async () => {
    const user = setup();
    const first = screen.getByLabelText("First name");
    await user.type(first, "!");
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1), SETTLE);

    // Blurring an unchanged field must not write again.
    await user.click(first);
    await user.tab();
    await new Promise((r) => setTimeout(r, 1200));
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("is loud about a failure and offers a retry", async () => {
    update.mockRejectedValueOnce(new Error("network"));
    const user = setup();
    await user.type(screen.getByLabelText("First name"), "!");

    const alert = await screen.findByRole("alert", undefined, SETTLE);
    expect(alert).toHaveTextContent(/couldn't save/i);

    update.mockResolvedValue({});
    await user.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText(/all changes saved/i)).toBeInTheDocument(), SETTLE);
  });

  it("ignores a stale response that lands after a newer one", async () => {
    // Two saves in flight: the first must not be allowed to report success
    // over the second, or the panel claims to have saved a value it didn't.
    let releaseFirst: () => void = () => {};
    update
      .mockImplementationOnce(() => new Promise((r) => { releaseFirst = () => r({}); }))
      .mockRejectedValueOnce(new Error("network"));

    const user = setup();
    await user.type(screen.getByLabelText("First name"), "!");
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1), SETTLE);
    await user.type(screen.getByLabelText("First name"), "?");
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2), SETTLE);

    // The second call failed; now let the first one resolve.
    await screen.findByRole("alert", undefined, SETTLE);
    releaseFirst();
    await new Promise((r) => setTimeout(r, 60));

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/all changes saved/i)).not.toBeInTheDocument();
  });
});
