import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Insight } from "../api/types";

const decide = vi.fn();

vi.mock("../api/intelligence", () => ({
  coachApi: {
    insights: vi.fn(),
    generate: vi.fn(),
    decide: (...args: unknown[]) => decide(...args),
  },
  intelligenceApi: {},
  suggestionsApi: {},
  automationApi: {},
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { tenant: { id: "t1", base_currency: "USD" } } }),
}));

import { useDecideInsight } from "./useCoach";

const FEED_KEY = ["coach-insights", "t1", "live"];

function insight(id: string, status: Insight["status"] = "new"): Insight {
  return {
    id,
    kind: "overspending",
    severity: "warning",
    status,
    title: `Insight ${id}`,
    body: "",
    rationale: "Because.",
    evidence: {},
    action: {},
    priority_score: 50,
    period_start: null,
    period_end: null,
    expires_on: null,
    provider: "RuleBasedCoach",
    provider_kind: "rule",
    provider_version: "1.0",
    related_transaction_id: null,
    related_category_id: null,
    related_account_id: null,
    created_at: "2026-06-15T09:00:00Z",
  };
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function feed(client: QueryClient) {
  return client.getQueryData<Insight[]>(FEED_KEY) ?? [];
}

beforeEach(() => vi.clearAllMocks());

describe("useDecideInsight — optimistic decisions", () => {
  it("removes a dismissed insight from the feed before the server replies", async () => {
    const client = makeClient();
    client.setQueryData(FEED_KEY, [insight("a"), insight("b")]);
    decide.mockReturnValue(new Promise(() => {})); // never settles

    const { result } = renderHook(() => useDecideInsight(), { wrapper: wrapper(client) });
    act(() => {
      result.current.mutate({ insightId: "a", decision: "dismiss" });
    });

    // Dismissing is the most common action here; waiting on a round-trip makes
    // the feed feel like a form.
    await waitFor(() => expect(feed(client).map((i) => i.id)).toEqual(["b"]));
  });

  it("keeps a bookmarked insight in the feed and flips its badge", async () => {
    const client = makeClient();
    client.setQueryData(FEED_KEY, [insight("a")]);
    decide.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useDecideInsight(), { wrapper: wrapper(client) });
    act(() => {
      result.current.mutate({ insightId: "a", decision: "bookmark" });
    });

    // A bookmark means "keep this in front of me" — the opposite of dismissal.
    await waitFor(() => expect(feed(client)[0].status).toBe("bookmarked"));
    expect(feed(client)).toHaveLength(1);
  });

  it("restores the feed exactly when the decision fails", async () => {
    const client = makeClient();
    client.setQueryData(FEED_KEY, [insight("a"), insight("b")]);
    decide.mockRejectedValue(new Error("offline"));

    const { result } = renderHook(() => useDecideInsight(), { wrapper: wrapper(client) });
    act(() => {
      result.current.mutate({ insightId: "a", decision: "dismiss" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    // A silently failed dismissal would have the card reappear later with no
    // explanation — worse than a slow dismissal.
    expect(feed(client).map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("treats 'acted' like a dismissal for feed purposes", async () => {
    const client = makeClient();
    client.setQueryData(FEED_KEY, [insight("a")]);
    decide.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useDecideInsight(), { wrapper: wrapper(client) });
    act(() => {
      result.current.mutate({ insightId: "a", decision: "acted" });
    });

    await waitFor(() => expect(feed(client)).toHaveLength(0));
  });
});
