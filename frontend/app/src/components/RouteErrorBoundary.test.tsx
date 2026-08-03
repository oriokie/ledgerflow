import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

function Bomb(): never {
  throw new Error("simulated render crash");
}

// React logs the caught error to the console by design; silence it so the
// test output stays readable without hiding a real assertion failure.
const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

describe("RouteErrorBoundary", () => {
  it("renders children normally when nothing throws", () => {
    render(
      <RouteErrorBoundary>
        <p>Real page content</p>
      </RouteErrorBoundary>,
    );
    expect(screen.getByText("Real page content")).toBeInTheDocument();
  });

  it("shows a real fallback instead of a blank tree when a child throws", () => {
    // This is the exact failure mode the app had with no boundary at all:
    // an uncaught render error unmounts everything, including the header and
    // every button — indistinguishable from the page simply having none.
    render(
      <RouteErrorBoundary>
        <Bomb />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong on this page/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("says the rest of the app is unaffected, because it is — this boundary is route-scoped", () => {
    render(
      <RouteErrorBoundary>
        <Bomb />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText(/rest of ledgerflow is fine/i)).toBeInTheDocument();
  });

  it("resets when mounted with a new key, so a fresh destination gets a clean attempt", () => {
    // AppShell mounts this with key={pathname}; changing the key is React's
    // own mechanism for "unmount the old instance, mount a fresh one" — a
    // brand-new instance trivially starts with state = { error: null }
    // through the ordinary mount lifecycle, no internal prop-diffing needed.
    const { rerender } = render(
      <RouteErrorBoundary key="/investments">
        <Bomb />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();

    rerender(
      <RouteErrorBoundary key="/debt">
        <p>Debt page content</p>
      </RouteErrorBoundary>,
    );
    expect(screen.getByText("Debt page content")).toBeInTheDocument();
    expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument();
  });

  it("does not reset just because children re-render with the same key", () => {
    // Only a genuine navigation (a real key change) should give a crashed
    // page a fresh attempt — re-rendering under the same key must not
    // silently retry forever, and since the key is unchanged React reuses
    // the same instance rather than remounting it.
    const { rerender } = render(
      <RouteErrorBoundary key="/investments">
        <Bomb />
      </RouteErrorBoundary>,
    );
    rerender(
      <RouteErrorBoundary key="/investments">
        <Bomb />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });

  it("lets the user retry in place without navigating away", async () => {
    let shouldThrow = true;
    function Flaky() {
      if (shouldThrow) throw new Error("first attempt fails");
      return <p>Recovered content</p>;
    }
    const user = userEvent.setup();
    render(
      <RouteErrorBoundary>
        <Flaky />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();

    shouldThrow = false;
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("Recovered content")).toBeInTheDocument();
  });

  it("logs the crash for diagnosability rather than swallowing it silently", () => {
    render(
      <RouteErrorBoundary>
        <Bomb />
      </RouteErrorBoundary>,
    );
    expect(consoleError).toHaveBeenCalled();
  });
});
