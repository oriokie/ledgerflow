import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Table } from ".";
import type { Column } from ".";

interface Row {
  id: string;
  name: string;
  amount: number;
}

const ROWS: Row[] = [
  { id: "1", name: "Groceries", amount: -8450 },
  { id: "2", name: "Salary", amount: 650000 },
];

const COLUMNS: Column<Row>[] = [
  { key: "name", header: "Name", render: (r) => r.name, sortable: true },
  { key: "amount", header: "Amount", align: "right", render: (r) => r.amount },
];

describe("Table", () => {
  it("renders headers and a cell per row", () => {
    render(<Table columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.getByRole("columnheader", { name: /name/i })).toBeInTheDocument();
    expect(screen.getByText("Groceries")).toBeInTheDocument();
    expect(screen.getByText("Salary")).toBeInTheDocument();
    // header row + 2 body rows
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("right-aligned columns get the amount class", () => {
    render(<Table columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.getByRole("columnheader", { name: /amount/i })).toHaveClass("lf-col-amount");
  });

  it("emits onSort with the column key when a sortable header is clicked", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    render(<Table columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} onSort={onSort} />);
    await user.click(screen.getByRole("columnheader", { name: /name/i }));
    expect(onSort).toHaveBeenCalledWith("name");
  });

  it("reflects the active sort direction via aria-sort", () => {
    render(
      <Table
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        sort={{ key: "name", direction: "asc" }}
        onSort={() => {}}
      />,
    );
    expect(screen.getByRole("columnheader", { name: /name/i })).toHaveAttribute("aria-sort", "ascending");
  });

  it("fires onRowClick with the row", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(<Table columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} onRowClick={onRowClick} />);
    await user.click(screen.getByText("Groceries"));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
  });
});
