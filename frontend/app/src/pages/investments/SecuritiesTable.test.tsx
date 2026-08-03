import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Security } from "../../api/types";
import { SecuritiesTable } from "./SecuritiesTable";

function security(overrides: Partial<Security> = {}): Security {
  return {
    id: "sec-1",
    symbol: "BONDKEDDD",
    name: "Kenya Bond",
    asset_class: "bond",
    sector: "",
    currency: "KES",
    exchange: "",
    ...overrides,
  } as Security;
}

describe("SecuritiesTable", () => {
  it("shows a tracked security before any trade exists", () => {
    // The reported bug: adding a security produced no visible change, so the
    // user re-added it and got "already tracked" — contradicting the screen.
    render(<SecuritiesTable securities={[security()]} />);

    expect(screen.getByText("BONDKEDDD")).toBeInTheDocument();
    expect(screen.getByText("Kenya Bond")).toBeInTheDocument();
    expect(screen.getByText("KES")).toBeInTheDocument();
  });

  it("renders the human label for an asset class, not the raw enum", () => {
    render(<SecuritiesTable securities={[security({ asset_class: "cash_equivalent" })]} />);
    expect(screen.getByText("Cash investments")).toBeInTheDocument();
    expect(screen.queryByText("cash_equivalent")).not.toBeInTheDocument();
  });

  it("falls back to the raw value for an unknown asset class", () => {
    // Better a slightly ugly label than a blank cell if the backend adds one.
    render(<SecuritiesTable securities={[security({ asset_class: "commodity" })]} />);
    expect(screen.getByText("commodity")).toBeInTheDocument();
  });

  it("renders an em dash for absent optional fields", () => {
    render(<SecuritiesTable securities={[security()]} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("says so plainly when there is nothing tracked", () => {
    render(<SecuritiesTable securities={[]} />);
    expect(screen.getByText(/no securities tracked/i)).toBeInTheDocument();
  });

  it("lists every security", () => {
    render(
      <SecuritiesTable
        securities={[
          security({ id: "1", symbol: "VTI" }),
          security({ id: "2", symbol: "BND" }),
          security({ id: "3", symbol: "BTC" }),
        ]}
      />,
    );
    expect(screen.getByText("VTI")).toBeInTheDocument();
    expect(screen.getByText("BND")).toBeInTheDocument();
    expect(screen.getByText("BTC")).toBeInTheDocument();
  });
});
