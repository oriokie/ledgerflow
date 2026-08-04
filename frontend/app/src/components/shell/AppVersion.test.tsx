import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppVersion } from "./AppVersion";

afterEach(() => vi.unstubAllEnvs());

describe("AppVersion", () => {
  it("shows the human release number, not the sha", () => {
    // "1.0.0" is what a person quotes in a bug report; a sha is what a
    // developer greps for. The rail carries the first, the title the second.
    vi.stubEnv("VITE_APP_VERSION", "1.0.0");
    vi.stubEnv("VITE_APP_RELEASE", "93ddaa316fcd0ae43bc5e1ede3642a23f1488b9d");
    render(<AppVersion />);
    expect(screen.getByText("v1.0.0")).toBeInTheDocument();
  });

  it("keeps the exact build reachable in the title", () => {
    vi.stubEnv("VITE_APP_VERSION", "1.0.0");
    vi.stubEnv("VITE_APP_RELEASE", "93ddaa3abc");
    const { container } = render(<AppVersion />);
    const el = container.querySelector(".lf-rail-version");
    expect(el?.getAttribute("title")).toContain("93ddaa3abc");
    expect(el?.getAttribute("title")).toContain("1.0.0");
  });

  it("says 'dev' rather than nothing outside a release build", () => {
    // An empty slot where a version belongs reads as a broken version
    // display, not as "this was not built by CI".
    vi.stubEnv("VITE_APP_VERSION", "");
    vi.stubEnv("VITE_APP_RELEASE", "");
    render(<AppVersion />);
    expect(screen.getByText("dev")).toBeInTheDocument();
  });

  it("a version without a build sha is still a dev build", () => {
    // The version file exists in every checkout; only CI supplies the sha.
    // Trusting the version alone would stamp local builds as releases.
    vi.stubEnv("VITE_APP_VERSION", "1.0.0");
    vi.stubEnv("VITE_APP_RELEASE", "");
    render(<AppVersion />);
    expect(screen.getByText("dev")).toBeInTheDocument();
  });
});
