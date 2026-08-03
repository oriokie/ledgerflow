import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useOpenOnParam } from "./useOpenOnParam";

function Probe() {
  const [open, setOpen] = useOpenOnParam();
  const location = useLocation();
  return (
    <div>
      <span data-testid="state">{open ? "open" : "closed"}</span>
      <span data-testid="search">{location.search}</span>
      <button onClick={() => setOpen(false)}>Dismiss</button>
      <button onClick={() => setOpen((v) => !v)}>Toggle</button>
    </div>
  );
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Probe />
    </MemoryRouter>,
  );
}

describe("useOpenOnParam", () => {
  it("stays closed without the flag", () => {
    renderAt("/budgets");
    expect(screen.getByTestId("state")).toHaveTextContent("closed");
  });

  it("opens when the flag is present", () => {
    renderAt("/budgets?add=1");
    expect(screen.getByTestId("state")).toHaveTextContent("open");
  });

  it("consumes the flag so a refresh or Back doesn't reopen a dismissed form", async () => {
    const user = userEvent.setup();
    renderAt("/budgets?add=1");

    // The flag is stripped from the URL immediately on mount.
    expect(screen.getByTestId("search")).not.toHaveTextContent("add=1");

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.getByTestId("state")).toHaveTextContent("closed");
  });

  it("leaves unrelated query params alone", () => {
    renderAt("/budgets?add=1&period=2026-01");
    expect(screen.getByTestId("search")).toHaveTextContent("period=2026-01");
    expect(screen.getByTestId("search")).not.toHaveTextContent("add=1");
  });

  it("supports updater callbacks like useState", async () => {
    const user = userEvent.setup();
    renderAt("/budgets");
    await user.click(screen.getByRole("button", { name: "Toggle" }));
    expect(screen.getByTestId("state")).toHaveTextContent("open");
  });
});
