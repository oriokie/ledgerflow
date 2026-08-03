import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Table } from ".";
import type { Column } from ".";

interface Row {
  id: string;
  name: string;
}

const ROWS: Row[] = [
  { id: "1", name: "Groceries" },
  { id: "2", name: "Salary" },
];

const COLUMNS: Column<Row>[] = [{ key: "name", header: "Name", render: (r) => r.name }];

describe("Table selection", () => {
  it("adds a checkbox column only when selection is wired up", () => {
    const { rerender } = render(<Table columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    rerender(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        selectedIds={new Set()}
        onToggleRow={() => {}}
      />,
    );
    // one per row + select-all
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  });

  it("marks selected rows via aria-selected so the state is announced", () => {
    render(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        selectedIds={new Set(["1"])}
        onToggleRow={() => {}}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
    expect(rows[1]).toHaveAttribute("aria-selected", "false");
  });

  it("shows an indeterminate select-all for a partial selection", () => {
    render(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        selectedIds={new Set(["1"])}
        onToggleRow={() => {}}
        onToggleAll={() => {}}
      />,
    );
    const selectAll = screen.getByRole("checkbox", { name: /select all/i }) as HTMLInputElement;
    expect(selectAll.indeterminate).toBe(true);
    expect(selectAll.checked).toBe(false);
  });

  it("emits the row id and the next selected state", async () => {
    const user = userEvent.setup();
    const onToggleRow = vi.fn();
    render(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        selectedIds={new Set()}
        onToggleRow={onToggleRow}
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: "Select row 1" }));
    expect(onToggleRow).toHaveBeenCalledWith("1", true);
  });

  it("does not fire the row click when the checkbox is used", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
        selectedIds={new Set()}
        onToggleRow={() => {}}
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: "Select row 1" }));
    expect(onRowClick).not.toHaveBeenCalled();
  });
});

describe("Table row actions", () => {
  it("renders per-row actions without swallowing the row click handler", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    const onEdit = vi.fn();
    render(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
        rowActions={(row) => <button onClick={() => onEdit(row.id)}>Edit {row.name}</button>}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Edit Groceries" }));
    expect(onEdit).toHaveBeenCalledWith("1");
    // The action is not a navigation — it must not also open the row.
    expect(onRowClick).not.toHaveBeenCalled();
  });
});

describe("Table empty state", () => {
  it("renders the empty slot instead of an empty grid", () => {
    render(
      <Table columns={COLUMNS} rows={[]} rowKey={(r) => r.id} empty={<p>No transactions yet</p>} />,
    );
    expect(screen.getByText("No transactions yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
