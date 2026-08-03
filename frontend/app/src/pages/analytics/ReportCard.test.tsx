import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ReportMeta, ReportResult } from "../../api/types";

vi.mock("recharts", () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Stub, AreaChart: Stub, LineChart: Stub, BarChart: Stub, PieChart: Stub,
    Area: () => null, Line: () => null, Bar: () => null, Pie: () => null, Cell: () => null,
    XAxis: () => null, YAxis: () => null, Tooltip: () => null, Legend: () => null,
  };
});

import { ReportCard } from "./ReportCard";

const META: ReportMeta = { slug: "cash_flow", title: "Cash flow", chart: "bar", group: "flow" };

const RESULT: ReportResult = {
  slug: "cash_flow",
  title: "Cash flow",
  currency: "USD",
  start: "2026-01-01",
  end: "2026-06-30",
  totals: { inflow_minor: 400_000, outflow_minor: 120_000, net_minor: 280_000 },
  series: [{ month: "2026-01-01", inflow_minor: 400_000, outflow_minor: 120_000 }],
  rows: [],
  meta: {},
};

function renderCard(props: Partial<React.ComponentProps<typeof ReportCard>> = {}) {
  return render(
    <ReportCard meta={META} result={RESULT} exportPath="/export.csv" {...props} />,
  );
}

// The export endpoints are tenant-scoped, so downloads go through the
// authenticated client rather than a bare anchor. Mocked here to assert the
// control calls it with the right path.
const downloadFile = vi.fn().mockResolvedValue(undefined);
vi.mock("../../lib/download", () => ({ downloadFile: (...a: unknown[]) => downloadFile(...a) }));

describe("ReportCard", () => {
  it("labels totals from the field names", () => {
    renderCard();
    expect(screen.getByText("Inflow")).toBeInTheDocument();
    expect(screen.getByText("Outflow")).toBeInTheDocument();
  });

  it("explains an absent result rather than rendering an empty chart", () => {
    // An empty chart reads as "you earned nothing" — a claim, not an absence.
    renderCard({ result: null });
    expect(screen.getByText(/nothing to show for this period/i)).toBeInTheDocument();
  });

  it("downloads through the authenticated client, not a bare link", async () => {
    // A plain <a href download> sends no Authorization or X-Tenant-ID header,
    // so every export previously returned 401 (and in dev silently saved
    // Vite's index.html under the report's filename).
    renderCard();
    const button = screen.getByRole("button", { name: /export cash flow/i });
    expect(button).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /export cash flow/i })).not.toBeInTheDocument();

    fireEvent.click(button);
    await waitFor(() => expect(downloadFile).toHaveBeenCalledWith("/export.csv", "cash_flow.csv"));
  });

  it("surfaces a partial-month caveat above the chart", () => {
    renderCard({ result: { ...RESULT, meta: { partial_month: true } } });
    expect(screen.getByText(/isn't over yet/i)).toBeInTheDocument();
  });

  it("renders a score report as a number out of 100", () => {
    renderCard({
      meta: { slug: "financial_health", title: "Financial health", chart: "score", group: "position" },
      result: { ...RESULT, totals: { score: 78 }, series: [] },
    });
    expect(screen.getByText("78")).toBeInTheDocument();
    expect(screen.getByText(/out of 100/i)).toBeInTheDocument();
  });

  it("renders tabular reports as a table with humanised headers", () => {
    renderCard({
      meta: { slug: "merchant_analytics", title: "Merchants", chart: "table", group: "spending" },
      result: {
        ...RESULT,
        totals: {},
        series: [],
        rows: [{ label: "Corner Shop", amount_minor: 12_500, count: 4 }],
      },
    });
    expect(screen.getByRole("columnheader", { name: "Label" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Amount" })).toBeInTheDocument();
    expect(screen.getByText("Corner Shop")).toBeInTheDocument();
  });

  it("hides identifier columns, which are for linking not reading", () => {
    renderCard({
      meta: { slug: "category_analytics", title: "Categories", chart: "table", group: "spending" },
      result: {
        ...RESULT,
        totals: {},
        series: [],
        rows: [{ category_id: "abc-123", label: "Groceries", amount_minor: 9_000 }],
      },
    });
    expect(screen.queryByText("abc-123")).not.toBeInTheDocument();
    expect(screen.getByText("Groceries")).toBeInTheDocument();
  });

  it("emits the row on drill-down", async () => {
    const user = userEvent.setup();
    const onDrillDown = vi.fn();
    renderCard({
      meta: { slug: "category_analytics", title: "Categories", chart: "table", group: "spending" },
      result: {
        ...RESULT,
        totals: {},
        series: [],
        rows: [{ category_id: "abc", label: "Groceries", amount_minor: 9_000 }],
      },
      onDrillDown,
    });

    await user.click(screen.getByText("Groceries"));
    expect(onDrillDown).toHaveBeenCalledWith(
      expect.objectContaining({ label: "Groceries" }),
    );
  });

  it("marks rows as interactive only when drill-down is wired", () => {
    const { container } = renderCard({
      meta: { slug: "merchant_analytics", title: "Merchants", chart: "table", group: "spending" },
      result: { ...RESULT, totals: {}, series: [], rows: [{ label: "Shop", amount_minor: 100 }] },
    });
    expect(container.querySelector("tr[data-clickable]")).not.toBeInTheDocument();
  });

  it("keeps the sign on a negative total", () => {
    // formatAmount() returns a magnitude; a -$450 deficit shown as "$450"
    // would read as a surplus.
    renderCard({
      meta: { slug: "cash_flow", title: "Cash flow", chart: "table", group: "flow" },
      result: {
        ...RESULT,
        totals: {},
        series: [],
        rows: [{ label: "March", net_minor: -45_000 }],
      },
    });
    // <Money> splits whole and cents into separate spans, so assert on the
    // row's text rather than a single node.
    const row = screen.getByText("March").closest("tr")!;
    expect(row.textContent).toMatch(/[−-]\$450/);
  });
});
