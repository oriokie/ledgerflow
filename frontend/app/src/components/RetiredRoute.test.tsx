import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { RetiredRoute } from "./RetiredRoute";
import { writeFlag } from "../lib/featureFlags";
import { RETIRED_PATHS } from "./shell/navConfigV2";

function Landed() {
  return <p>landed</p>;
}
function Legacy() {
  return <p>legacy bills page</p>;
}

/** Renders the retired path and reports where the router ended up. */
function go(path: string, initial: string) {
  render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path={path} element={<RetiredRoute path={path} legacy={<Legacy />} />} />
        <Route path="/plan" element={<Landed />} />
        <Route path="/activity" element={<Landed />} />
        <Route path="/insights" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => writeFlag("navV2", true));
afterEach(() => localStorage.clear());

describe("retired paths", () => {
  it("serves the old page when the flag is off", () => {
    writeFlag("navV2", false);
    go("/bills", "/bills");
    expect(screen.getByText("legacy bills page")).toBeInTheDocument();
  });

  it("every retired path has a destination", () => {
    // The roadmap's exit criterion, as an assertion: no bookmark 404s.
    for (const [from, to] of Object.entries(RETIRED_PATHS)) {
      expect(from.startsWith("/")).toBe(true);
      expect(to.startsWith("/")).toBe(true);
    }
    expect(Object.keys(RETIRED_PATHS)).toHaveLength(8);
  });

  it("lands on the right tab, not a generic hub", () => {
    // "/bills → /plan" would be a redirect that still loses the user.
    expect(RETIRED_PATHS["/bills"]).toBe("/plan?tab=bills");
    expect(RETIRED_PATHS["/recurring"]).toBe("/plan?tab=recurring");
    expect(RETIRED_PATHS["/analytics"]).toBe("/insights?tab=trends");
  });

  it("redirects when the flag is on", () => {
    go("/bills", "/bills");
    expect(screen.getByText("landed")).toBeInTheDocument();
    expect(screen.queryByText("legacy bills page")).not.toBeInTheDocument();
  });

  it("keeps a deep link's own query when the path moves", () => {
    // `/transactions?category=abc` is a filter someone saved. Dropping it on
    // the way to `/activity` would silently show them everything instead.
    render(
      <MemoryRouter initialEntries={["/transactions?category=abc"]}>
        <Routes>
          <Route
            path="/transactions"
            element={<RetiredRoute path="/transactions" legacy={<Legacy />} />}
          />
          <Route path="/activity" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("search")).toHaveTextContent("category=abc");
  });

  it("lets an explicit tab in the URL beat the default", () => {
    render(
      <MemoryRouter initialEntries={["/bills?tab=cashflow"]}>
        <Routes>
          <Route path="/bills" element={<RetiredRoute path="/bills" legacy={<Legacy />} />} />
          <Route path="/plan" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("search")).toHaveTextContent("tab=cashflow");
  });
});

/** MemoryRouter keeps its history in memory, so the assertion has to read the
 * router's location rather than `window.location`. */
function LocationProbe() {
  const { pathname, search } = useLocation();
  return <p data-testid="search">{`${pathname}${search}`}</p>;
}
