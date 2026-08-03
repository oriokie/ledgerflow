import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  currentPermission,
  existingSubscriptionEndpoint,
  isPushSupported,
  subscribeToPush,
  unsubscribeFromPush,
} from "./pushSubscription";

// jsdom implements the DOM/HTML spec, not the Push API — it has no
// `window.PushManager` at all, so `isPushSupported()` would be false for
// every test in this file without an explicit stub. This mirrors what every
// real supporting browser (Chrome, Firefox, Edge, Android WebView) actually
// provides; only the test environment is missing it.
beforeAll(() => {
  if (!("PushManager" in window)) {
    Object.defineProperty(window, "PushManager", { value: class {}, configurable: true });
  }
});

describe("isPushSupported", () => {
  // jsdom implements neither the Service Worker nor Push APIs at all — both
  // are stubbed explicitly here rather than assumed, which is the honest
  // state of the test environment (every real supporting browser provides
  // both natively; only jsdom is missing them).
  it("is true once both serviceWorker and PushManager are present", () => {
    Object.defineProperty(navigator, "serviceWorker", { value: {}, configurable: true });
    expect(isPushSupported()).toBe(true);
  });

  it("is false without serviceWorker support", () => {
    const original = navigator.serviceWorker;
    // @ts-expect-error -- deliberately simulating an unsupporting browser
    delete navigator.serviceWorker;
    expect(isPushSupported()).toBe(false);
    Object.defineProperty(navigator, "serviceWorker", { value: original, configurable: true });
  });
});

// Mutating the real `navigator.serviceWorker` in place (rather than replacing
// `navigator` or `window` wholesale via vi.stubGlobal, which proved to
// corrupt jsdom's global object model for later tests in this environment).
function stubServiceWorker(registration: {
  pushManager: { subscribe?: ReturnType<typeof vi.fn>; getSubscription: ReturnType<typeof vi.fn> };
}) {
  Object.defineProperty(navigator, "serviceWorker", {
    value: { ready: Promise.resolve(registration) },
    configurable: true,
  });
}

const originalServiceWorker = navigator.serviceWorker;
afterEach(() => {
  Object.defineProperty(navigator, "serviceWorker", {
    value: originalServiceWorker,
    configurable: true,
  });
  vi.unstubAllGlobals();
});

describe("currentPermission", () => {
  it("reports the browser's current permission when push is supported", async () => {
    vi.stubGlobal("Notification", { permission: "default", requestPermission: vi.fn() });
    expect(await currentPermission()).toBe("default");
  });
});

describe("subscribeToPush", () => {
  beforeEach(() => {
    vi.stubGlobal("Notification", { requestPermission: vi.fn(), permission: "default" });
  });

  it("returns null when the user declines the permission prompt", async () => {
    // Never subscribes without permission — asking again wouldn't help, and
    // the caller shouldn't have to distinguish "declined" from "failed".
    const subscribe = vi.fn();
    (Notification.requestPermission as ReturnType<typeof vi.fn>).mockResolvedValue("denied");
    stubServiceWorker({ pushManager: { subscribe, getSubscription: vi.fn() } });

    const result = await subscribeToPush("some-key");
    expect(result).toBeNull();
    expect(subscribe).not.toHaveBeenCalled();
  });

  it("subscribes and returns the endpoint plus keys once granted", async () => {
    (Notification.requestPermission as ReturnType<typeof vi.fn>).mockResolvedValue("granted");
    const subscribe = vi.fn().mockResolvedValue({
      toJSON: () => ({
        endpoint: "https://push.example.com/abc",
        keys: { p256dh: "p-key", auth: "a-key" },
      }),
    });
    stubServiceWorker({ pushManager: { subscribe, getSubscription: vi.fn() } });

    const result = await subscribeToPush("some-key");
    expect(result).toEqual({
      endpoint: "https://push.example.com/abc",
      keys: { p256dh: "p-key", auth: "a-key" },
    });
  });

  it("returns null rather than a half-formed object if the browser omits a key", async () => {
    (Notification.requestPermission as ReturnType<typeof vi.fn>).mockResolvedValue("granted");
    const subscribe = vi.fn().mockResolvedValue({
      toJSON: () => ({ endpoint: "https://push.example.com/abc", keys: {} }),
    });
    stubServiceWorker({ pushManager: { subscribe, getSubscription: vi.fn() } });

    expect(await subscribeToPush("some-key")).toBeNull();
  });
});

describe("unsubscribeFromPush", () => {
  it("returns null when there was nothing subscribed", async () => {
    stubServiceWorker({ pushManager: { getSubscription: vi.fn().mockResolvedValue(null) } });
    expect(await unsubscribeFromPush()).toBeNull();
  });

  it("unsubscribes and returns the removed endpoint", async () => {
    const unsubscribe = vi.fn().mockResolvedValue(true);
    stubServiceWorker({
      pushManager: {
        getSubscription: vi.fn().mockResolvedValue({
          endpoint: "https://push.example.com/xyz",
          unsubscribe,
        }),
      },
    });
    expect(await unsubscribeFromPush()).toBe("https://push.example.com/xyz");
    expect(unsubscribe).toHaveBeenCalled();
  });
});

describe("existingSubscriptionEndpoint", () => {
  it("returns the current endpoint when already subscribed", async () => {
    stubServiceWorker({
      pushManager: {
        getSubscription: vi.fn().mockResolvedValue({ endpoint: "https://push.example.com/already" }),
      },
    });
    expect(await existingSubscriptionEndpoint()).toBe("https://push.example.com/already");
  });

  it("returns null when nothing is subscribed", async () => {
    stubServiceWorker({ pushManager: { getSubscription: vi.fn().mockResolvedValue(null) } });
    expect(await existingSubscriptionEndpoint()).toBeNull();
  });
});
