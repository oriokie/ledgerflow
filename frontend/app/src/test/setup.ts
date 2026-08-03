// Polyfills IndexedDB for jsdom, which ships none — used by the offline
// queue (src/lib/offlineQueue.ts) and its tests.
import "fake-indexeddb/auto";

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library doesn't auto-clean between tests under Vitest.
afterEach(() => cleanup());

/**
 * jsdom implements the <dialog> element but not its modal behavior, so
 * `showModal()` / `close()` are missing entirely. Our Modal and CommandPalette
 * both rely on the native dialog for focus containment and Esc-to-close — the
 * right call in the browser — which would otherwise make them untestable.
 *
 * This shim gives jsdom just enough: toggling `open` and firing the `close`
 * event, so component tests exercise the real open/close wiring. It does not
 * emulate focus trapping or the top layer; those are the platform's job and
 * are not ours to assert.
 */
if (typeof HTMLDialogElement !== "undefined") {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.open = true;
    };
  }
  if (!HTMLDialogElement.prototype.show) {
    HTMLDialogElement.prototype.show = function show(this: HTMLDialogElement) {
      this.open = true;
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement, returnValue?: string) {
      this.open = false;
      if (returnValue !== undefined) this.returnValue = returnValue;
      this.dispatchEvent(new Event("close"));
    };
  }
}
