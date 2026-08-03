import { describe, expect, it } from "vitest";
import { GOTO_ROUTES, isTypingTarget, matchShortcut, SHORTCUTS } from "./shortcuts";

describe("isTypingTarget", () => {
  it("recognises the real text-entry elements", () => {
    for (const tag of ["input", "textarea", "select"]) {
      expect(isTypingTarget(document.createElement(tag))).toBe(true);
    }
  });

  it("recognises contenteditable and custom textbox widgets", () => {
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    // jsdom doesn't derive isContentEditable from the attribute.
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isTypingTarget(editable)).toBe(true);

    const widget = document.createElement("div");
    widget.setAttribute("role", "textbox");
    expect(isTypingTarget(widget)).toBe(true);
  });

  it("does not treat ordinary elements or null as typing surfaces", () => {
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe("matchShortcut — chords", () => {
  it("opens the palette on ⌘K and Ctrl+K", () => {
    expect(matchShortcut({ key: "k", metaKey: true })).toEqual({ type: "palette" });
    expect(matchShortcut({ key: "K", ctrlKey: true })).toEqual({ type: "palette" });
  });

  it("still opens the palette while the user is typing", () => {
    // A modifier means the user is deliberately reaching past the field.
    expect(matchShortcut({ key: "k", metaKey: true, typing: true })).toEqual({ type: "palette" });
  });
});

describe("matchShortcut — bare keys", () => {
  it("maps the action keys", () => {
    expect(matchShortcut({ key: "n" })).toEqual({ type: "new-transaction" });
    expect(matchShortcut({ key: "a" })).toEqual({ type: "new-account" });
    expect(matchShortcut({ key: "?" })).toEqual({ type: "help" });
  });

  it("never fires while the user is typing", () => {
    // The classic bug: unable to type "next month" in a memo because `n`
    // opened a dialog.
    for (const key of ["n", "a", "g", "?"]) {
      expect(matchShortcut({ key, typing: true })).toBeNull();
    }
  });

  it("ignores bare keys that carry a modifier", () => {
    expect(matchShortcut({ key: "n", metaKey: true })).toBeNull();
    expect(matchShortcut({ key: "a", altKey: true })).toBeNull();
  });

  it("returns null for unmapped keys", () => {
    expect(matchShortcut({ key: "z" })).toBeNull();
  });
});

describe("matchShortcut — the g prefix", () => {
  it("arms on g", () => {
    expect(matchShortcut({ key: "g" })).toEqual({ type: "await-goto" });
  });

  it("resolves every documented destination", () => {
    for (const [key, to] of Object.entries(GOTO_ROUTES)) {
      expect(matchShortcut({ key, pendingGoto: true })).toEqual({ type: "goto", to });
    }
  });

  it("prefers the prefix over the standalone meaning of the same key", () => {
    // `a` alone is New account; `g` then `a` must be Go to accounts.
    expect(matchShortcut({ key: "a", pendingGoto: true })).toEqual({ type: "goto", to: "/accounts" });
  });

  it("returns null for an unmapped second key", () => {
    expect(matchShortcut({ key: "z", pendingGoto: true })).toBeNull();
  });
});

describe("the documented sheet matches the implementation", () => {
  it("documents every g-prefixed route", () => {
    const documented = SHORTCUTS.filter((s) => s.keys.startsWith("G then"));
    expect(documented).toHaveLength(Object.keys(GOTO_ROUTES).length);
  });

  it("documents a resolvable action for each listed shortcut key", () => {
    // Guards against the sheet drifting from what actually works — a shortcut
    // list that lies is worse than no list.
    for (const s of SHORTCUTS.filter((x) => x.keys.length === 1)) {
      expect(matchShortcut({ key: s.keys.toLowerCase() })).not.toBeNull();
    }
  });
});
