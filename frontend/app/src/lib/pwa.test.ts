import { beforeEach, describe, expect, it, vi } from "vitest";
import { isInstallable, isRunningStandalone, promptInstall } from "./pwa";

describe("isRunningStandalone", () => {
  it("detects standalone display mode", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
    } as MediaQueryList);
    expect(isRunningStandalone()).toBe(true);
  });

  it("returns false in an ordinary browser tab", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: false,
    } as MediaQueryList);
    expect(isRunningStandalone()).toBe(false);
  });

  it("falls back to iOS Safari's non-standard navigator.standalone flag", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false } as MediaQueryList);
    Object.defineProperty(navigator, "standalone", { value: true, configurable: true });
    expect(isRunningStandalone()).toBe(true);
    Object.defineProperty(navigator, "standalone", { value: undefined, configurable: true });
  });
});

describe("install prompt", () => {
  beforeEach(async () => {
    // Reset the module-level captured prompt between tests by exhausting it.
    await promptInstall();
  });

  it("is not installable until the browser offers a prompt", () => {
    expect(isInstallable()).toBe(false);
  });

  it("prompting with nothing captured resolves to false rather than throwing", async () => {
    // The browser may never fire beforeinstallprompt at all (already
    // installed, unsupported browser) — calling promptInstall() then must be
    // a safe no-op, not an error the caller has to guard against.
    await expect(promptInstall()).resolves.toBe(false);
  });
});
