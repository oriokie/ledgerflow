import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppVersion } from "./AppVersion";

afterEach(() => vi.unstubAllEnvs());

describe("AppVersion", () => {
  it("shows the commit a release build came from, shortened", () => {
    vi.stubEnv("VITE_APP_RELEASE", "93ddaa316fcd0ae43bc5e1ede3642a23f1488b9d");
    render(<AppVersion />);
    expect(screen.getByText("93ddaa3")).toBeInTheDocument();
  });

  it("keeps the full sha reachable without cluttering the rail", () => {
    const sha = "93ddaa316fcd0ae43bc5e1ede3642a23f1488b9d";
    vi.stubEnv("VITE_APP_RELEASE", sha);
    const { container } = render(<AppVersion />);
    expect(container.querySelector(`[title="${sha}"]`)).not.toBeNull();
  });

  it("says 'dev' rather than nothing outside a release build", () => {
    // An empty slot where a version belongs reads as a broken version display,
    // not as "this was not built by CI".
    vi.stubEnv("VITE_APP_RELEASE", "");
    render(<AppVersion />);
    expect(screen.getByText("dev")).toBeInTheDocument();
  });
});
