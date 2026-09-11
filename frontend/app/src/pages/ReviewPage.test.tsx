import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { tenant: { id: "t1" } } }),
}));

vi.mock("../api/client", () => ({
  api: { get: vi.fn().mockResolvedValue(null) },
  ApiError: class ApiError extends Error {
    detail = "";
  },
}));

import { ReviewPage } from "./ReviewPage";

function renderReview(path: string, embedded = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ReviewPage embedded={embedded} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ReviewPage", () => {
  it("keeps its own title off the insights hub", () => {
    renderReview("/insights?tab=review", true);
    expect(screen.queryByRole("heading", { name: /financial review/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/review period/i)).toBeInTheDocument();
  });

  it("honours a period deep-link even outside the default window", () => {
    renderReview("/review?period=1999-01");
    expect(screen.getByRole("heading", { name: /financial review/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/review period/i)).toHaveValue("1999-01");
  });
});
