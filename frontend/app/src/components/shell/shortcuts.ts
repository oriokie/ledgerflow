/**
 * Global keyboard shortcuts.
 *
 * Two families, matching the conventions people already know from Linear,
 * Notion, Superhuman and GitHub:
 *
 *   • Chords    — ⌘K / Ctrl+K. Work everywhere, including inside text fields,
 *                 because a modifier means the user is deliberately reaching
 *                 past whatever they're typing in.
 *   • Bare keys — `n`, `?`, and `g`-prefixed navigation. These must NEVER fire
 *                 while the user is typing, or the letter `n` becomes
 *                 impossible to enter in a memo field.
 *
 * The matching logic lives here rather than in a component so it can be tested
 * directly — keyboard handling is exactly the kind of thing that silently rots
 * when it's only reachable through a rendered tree.
 */

export interface Shortcut {
  /** Display form, e.g. "G then T". */
  keys: string;
  label: string;
  group: "Navigation" | "Actions" | "General";
}

/** The shortcut sheet shown by `?`. Order is the display order. */
export const SHORTCUTS: Shortcut[] = [
  { keys: "⌘K", label: "Open the command palette", group: "General" },
  { keys: "?", label: "Show keyboard shortcuts", group: "General" },
  { keys: "Esc", label: "Close a dialog or panel", group: "General" },
  { keys: "N", label: "New transaction", group: "Actions" },
  { keys: "A", label: "New account", group: "Actions" },
  { keys: "G then D", label: "Go to Overview", group: "Navigation" },
  { keys: "G then T", label: "Go to Transactions", group: "Navigation" },
  { keys: "G then A", label: "Go to Accounts", group: "Navigation" },
  { keys: "G then B", label: "Go to Budgets", group: "Navigation" },
  { keys: "G then G", label: "Go to Goals", group: "Navigation" },
  { keys: "G then S", label: "Go to Settings", group: "Navigation" },
];

/** Destinations reachable by the `g` prefix. */
export const GOTO_ROUTES: Record<string, string> = {
  d: "/",
  t: "/transactions",
  a: "/accounts",
  b: "/budgets",
  g: "/goals",
  s: "/settings",
};

/**
 * True when the event originated somewhere the user is entering text.
 *
 * Without this, every bare-key shortcut would hijack ordinary typing — the
 * classic bug where you cannot write "next month" in a memo because `n` opened
 * a dialog. `isContentEditable` covers rich-text surfaces, and `role="textbox"`
 * covers custom widgets that aren't real inputs.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target.getAttribute("role") === "textbox") return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export type ShortcutAction =
  | { type: "palette" }
  | { type: "help" }
  | { type: "new-transaction" }
  | { type: "new-account" }
  | { type: "goto"; to: string }
  | { type: "await-goto" }
  | null;

interface MatchOptions {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  /** Whether the previous keypress was the `g` prefix. */
  pendingGoto?: boolean;
  /** Whether focus is currently in a text-entry surface. */
  typing?: boolean;
}

/**
 * Resolves a keypress to an action, or null for "not a shortcut".
 *
 * Pure and synchronous by design: the component layer only has to translate the
 * result into navigation or state, and every branch here is directly testable.
 */
export function matchShortcut(opts: MatchOptions): ShortcutAction {
  const { key, metaKey, ctrlKey, altKey, pendingGoto, typing } = opts;
  const lower = key.toLowerCase();

  // Chords first — a modifier means "reach past whatever I'm doing".
  if ((metaKey || ctrlKey) && lower === "k") return { type: "palette" };

  // Everything below is a bare key.
  if (metaKey || ctrlKey || altKey) return null;
  if (typing) return null;

  // Resolve a pending `g` prefix before anything else, so `g` then `a` is
  // "go to accounts" rather than "new account".
  if (pendingGoto) {
    const to = GOTO_ROUTES[lower];
    return to ? { type: "goto", to } : null;
  }

  if (lower === "g") return { type: "await-goto" };
  if (key === "?") return { type: "help" };
  if (lower === "n") return { type: "new-transaction" };
  if (lower === "a") return { type: "new-account" };

  return null;
}
