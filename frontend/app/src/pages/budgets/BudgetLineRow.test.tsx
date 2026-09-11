import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BudgetLineStatus } from "../../api/types";
import { BudgetLineRow } from "./BudgetLineRow";

const LINE: BudgetLineStatus = {
  line_id: "l1",
  category_id: "c1",
  category_name: "Groceries",
  limit_minor: 10000,
  carried_minor: 0,
  effective_limit_minor: 10000,
  actual_minor: 4000,
  remaining_minor: 6000,
  percent_used: 40,
  over_budget: false,
  rollover: false,
};

function setup(over: Partial<{ onUpdateLimit: ReturnType<typeof vi.fn>; onRemove: ReturnType<typeof vi.fn>; onToggleRollover: ReturnType<typeof vi.fn> }> = {}) {
  const onUpdateLimit = over.onUpdateLimit ?? vi.fn().mockResolvedValue(undefined);
  const onRemove = over.onRemove ?? vi.fn().mockResolvedValue(undefined);
  const onToggleRollover = over.onToggleRollover;
  render(
    <BudgetLineRow
      line={LINE}
      currency="USD"
      pacePercent={50}
      onUpdateLimit={onUpdateLimit}
      onRemove={onRemove}
      onToggleRollover={onToggleRollover}
    />,
  );
  return { onUpdateLimit, onRemove, onToggleRollover };
}

describe("BudgetLineRow", () => {
  it("renders a progressbar reflecting percent used", () => {
    setup();
    expect(screen.getByRole("progressbar", { name: /groceries/i })).toHaveAttribute("aria-valuenow", "40");
  });

  it("edits the limit inline and saves in minor units", async () => {
    const { onUpdateLimit } = setup();
    fireEvent.click(screen.getByRole("button", { name: /edit groceries limit/i }));

    const input = screen.getByLabelText(/new limit for groceries/i) as HTMLInputElement;
    expect(input.value).toBe("100"); // 10000 minor → 100 major
    fireEvent.change(input, { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onUpdateLimit).toHaveBeenCalledWith("l1", 15000));
  });

  it("removes only after a confirm step", async () => {
    const { onRemove } = setup();
    fireEvent.click(screen.getByRole("button", { name: /remove groceries/i }));
    expect(onRemove).not.toHaveBeenCalled(); // first click just asks to confirm

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(onRemove).toHaveBeenCalledWith("l1"));
  });

  it("toggles leftover carry when the switch is provided", async () => {
    const onToggleRollover = vi.fn().mockResolvedValue(undefined);
    setup({ onToggleRollover });
    fireEvent.click(screen.getByRole("switch", { name: /carry leftover/i }));
    await waitFor(() => expect(onToggleRollover).toHaveBeenCalledWith("l1", true));
  });
});
