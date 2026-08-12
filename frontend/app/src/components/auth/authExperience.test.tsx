import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoggedOutPage } from "../../pages/LoggedOutPage";
import { FINANCE_QUOTES, QUOTE_ROTATE_MS, initialQuoteIndex, nextQuoteIndex } from "./financeQuotes";
import { QuoteRotator } from "./QuoteRotator";

describe("financeQuotes", () => {
  it("provides a healthy set of attributed quotes", () => {
    expect(FINANCE_QUOTES.length).toBeGreaterThanOrEqual(10);
    for (const q of FINANCE_QUOTES) {
      expect(q.text.length).toBeGreaterThan(10);
      expect(q.author.length).toBeGreaterThan(2);
    }
  });

  it("wraps rotation and derives a stable start index", () => {
    expect(nextQuoteIndex(FINANCE_QUOTES.length - 1)).toBe(0);
    const idx = initialQuoteIndex(1234567890123);
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(idx).toBeLessThan(FINANCE_QUOTES.length);
  });
});

describe("QuoteRotator", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows a quote and rotates to the next one over time", () => {
    vi.setSystemTime(0); // start deterministically at quote 0
    render(<QuoteRotator />);
    expect(screen.getByText(`— ${FINANCE_QUOTES[0].author}`)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(QUOTE_ROTATE_MS + 300);
    });
    expect(screen.getByText(`— ${FINANCE_QUOTES[1].author}`)).toBeInTheDocument();
  });
});

describe("LoggedOutPage", () => {
  it("closes the session warmly with one clear way back in", () => {
    render(
      <MemoryRouter>
        <LoggedOutPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: /see you next time/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to home/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: /sign back in/i })).toHaveAttribute("href", "/login");
  });
});
