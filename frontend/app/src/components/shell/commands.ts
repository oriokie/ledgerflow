import { NAV_ITEMS } from "./navConfig";
import { INSIGHT_TABS, NAV_ITEMS_V2, PLAN_TABS } from "./navConfigV2";
import { readFlag } from "../../lib/featureFlags";

/** Result groups, in the order the palette renders them. */
export type CommandGroup = "Actions" | "Go to";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  to: string;
  keywords?: string;
  group?: CommandGroup;
}

/**
 * Quick actions surfaced above plain navigation.
 *
 * Each one is a *verb* the user can complete from anywhere — the palette's
 * job is to remove the "navigate there first, then click the button" step.
 * Keywords carry the synonyms people actually type ("move money" for a
 * transfer, "csv" for an import) so the match doesn't depend on knowing our
 * vocabulary.
 */
export const QUICK_ACTIONS: Command[] = [
  {
    id: "action-add-transaction",
    label: "New transaction",
    hint: "Action",
    to: "/transactions?add=1",
    keywords: "new record spend income add entry",
    group: "Actions",
  },
  {
    id: "action-new-account",
    label: "New account",
    hint: "Action",
    to: "/accounts?add=1",
    keywords: "open bank card cash institution add",
    group: "Actions",
  },
  {
    id: "action-transfer",
    label: "Transfer money",
    hint: "Action",
    to: "/transactions?add=1&type=transfer",
    keywords: "move between accounts send",
    group: "Actions",
  },
  {
    id: "action-create-budget",
    label: "Create budget",
    hint: "Action",
    to: "/budgets?add=1",
    keywords: "envelope plan cap allocate limit",
    group: "Actions",
  },
  {
    id: "action-create-goal",
    label: "Create goal",
    hint: "Action",
    to: "/goals?add=1",
    keywords: "save target fund milestone",
    group: "Actions",
  },
  {
    id: "action-add-bill",
    label: "Add a bill",
    hint: "Action",
    to: "/bills?add=1",
    keywords: "due payment subscription reminder",
    group: "Actions",
  },
  {
    id: "action-import",
    label: "Import transactions",
    hint: "Action",
    to: "/transactions?import=1",
    keywords: "csv upload ofx statement bank file",
    group: "Actions",
  },
];

const NAV_COMMANDS: Command[] = NAV_ITEMS.map((item) => ({
  id: `nav-${item.to}`,
  label: item.label,
  hint: "Go to",
  to: item.to,
  group: "Go to" as const,
}));

/**
 * Destinations under the Phase 5 IA — the eight rail entries, **plus every tab
 * that stopped being a top-level destination.**
 *
 * That second part is the point. The one real cost of collapsing 21
 * destinations into 8 is that someone who typed "bills" into the palette and
 * pressed Enter now has to know it lives inside Plan. Listing the tabs as
 * first-class jump targets means they don't: "bills" still matches, still
 * takes one keystroke and Enter, and lands on `/plan?tab=bills`. The palette
 * is what keeps a flatter rail from costing anybody speed.
 */
const NAV_COMMANDS_V2: Command[] = [
  ...NAV_ITEMS_V2.map((item) => ({
    id: `nav2-${item.to}`,
    label: item.label,
    hint: "Go to",
    to: item.to,
    group: "Go to" as const,
  })),
  ...PLAN_TABS.map((tab) => ({
    id: `nav2-plan-${tab.value}`,
    label: tab.label,
    hint: "In Plan",
    to: `/plan?tab=${tab.value}`,
    keywords: `plan ${tab.value}`,
    group: "Go to" as const,
  })),
  ...INSIGHT_TABS.map((tab) => ({
    id: `nav2-insights-${tab.value}`,
    label: tab.label,
    hint: "In Insights",
    to: `/insights?tab=${tab.value}`,
    keywords: `insights ${tab.value}${tab.value === "trends" ? " analytics" : ""}${tab.value === "coach" ? " coach" : ""}`,
    group: "Go to" as const,
  })),
];

/** Quick actions first, then every navigation destination. */
export const ALL_COMMANDS: Command[] = [...QUICK_ACTIONS, ...NAV_COMMANDS];
export const ALL_COMMANDS_V2: Command[] = [...QUICK_ACTIONS, ...NAV_COMMANDS_V2];

/** What a leading sigil narrows the palette to. */
export type Sigil = ">" | "@" | "#" | "$";

export interface ParsedQuery {
  sigil: Sigil | null;
  text: string;
  /** For `$`: a minor-unit amount filter the transactions endpoint understands. */
  amount?: { min?: number; max?: number };
}

/**
 * Sigils narrow the palette to one kind of thing.
 *
 * With no sigil the palette searches everything, which is right for the common
 * case — most people type a word, not a syntax. The sigils exist for the
 * moment you already know the *kind* of thing you want and the plain search is
 * returning four groups of it: `@` accounts, `#` categories, `>` actions,
 * `$` amounts.
 *
 * `$` is the one that earns its keep, because there is no other way to ask the
 * question at all: `$>500` finds transactions over 500, `$<20` under 20,
 * `$100-250` between. It maps onto `min_amount_minor` / `max_amount_minor`, so
 * the filter runs on the server against the whole ledger rather than against
 * whatever page happened to be loaded — a client-side version would quietly
 * answer a different question.
 */
export function parseQuery(raw: string): ParsedQuery {
  const trimmed = raw.trimStart();
  const sigil = (["@", "#", ">", "$"] as const).find((c) => trimmed.startsWith(c));
  if (!sigil) return { sigil: null, text: raw.trim() };

  const rest = trimmed.slice(1).trim();
  if (sigil !== "$") return { sigil, text: rest };

  return { sigil: "$", text: rest, amount: parseAmount(rest) };
}

/** `>500` | `<20` | `100-250` | `500`, in major units, returned as minor. */
function parseAmount(text: string): { min?: number; max?: number } | undefined {
  const clean = text.replace(/[, ]/g, "");
  const minor = (n: string) => Math.round(Number(n) * 100);

  let m = /^>=?(\d+(?:\.\d+)?)$/.exec(clean);
  if (m) return { min: minor(m[1]) };

  m = /^<=?(\d+(?:\.\d+)?)$/.exec(clean);
  if (m) return { max: minor(m[1]) };

  m = /^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$/.exec(clean);
  if (m) return { min: minor(m[1]), max: minor(m[2]) };

  // A bare number is read as "about this much" rather than "exactly": an exact
  // cent match almost never finds anything, and the user's intent is a lookup.
  m = /^(\d+(?:\.\d+)?)$/.exec(clean);
  if (m) {
    const v = minor(m[1]);
    return { min: Math.round(v * 0.9), max: Math.round(v * 1.1) };
  }
  return undefined;
}

/** Case-insensitive substring match over each command's label and keywords.
 * An empty query returns everything (the palette's resting state). */
export function filterCommands(query: string): Command[] {
  const { sigil, text } = parseQuery(query);
  // A record sigil is a statement that you want records, not destinations.
  if (sigil === "@" || sigil === "#" || sigil === "$") return [];

  const pool = readFlag("navV2") ? ALL_COMMANDS_V2 : ALL_COMMANDS;
  const scoped = sigil === ">" ? pool.filter((c) => c.group === "Actions") : pool;
  const q = text.toLowerCase();
  const matched = q
    ? scoped.filter((c) => `${c.label} ${c.keywords ?? ""}`.toLowerCase().includes(q))
    : scoped;
  return rankByUse(matched);
}

/** Groups a flat command list for sectioned rendering, preserving order and
 * dropping empty groups. */
export function groupCommands(commands: Command[]): { group: string; items: Command[] }[] {
  const order: string[] = ["Actions", "Go to"];
  const buckets = new Map<string, Command[]>();
  for (const cmd of commands) {
    const key = cmd.group ?? "Go to";
    const bucket = buckets.get(key);
    if (bucket) bucket.push(cmd);
    else buckets.set(key, [cmd]);
  }
  return order
    .filter((g) => buckets.has(g))
    .map((g) => ({ group: g, items: buckets.get(g)! }));
}


/* ==========================================================================
   Recent and frequent
   --------------------------------------------------------------------------
   Alphabetical order is a property of the list, not of the user. Someone who
   opens Activity forty times a week and Debt twice should not have to scroll
   past Debt. This keeps a small usage tally per command id and ranks matches
   by it — recency breaking ties, so a destination you have just started using
   climbs immediately instead of waiting to out-count a year of history.
   ========================================================================== */

const USE_KEY = "lf-command-use";
const HALF_LIFE_DAYS = 30;

interface UseRecord {
  count: number;
  last: number;
}

function readUse(): Record<string, UseRecord> {
  try {
    const raw = localStorage.getItem(USE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Record<string, UseRecord>) : {};
  } catch {
    return {};
  }
}

/** Called when a command is chosen. */
export function recordCommandUse(id: string): void {
  try {
    const use = readUse();
    const prev = use[id];
    use[id] = { count: (prev?.count ?? 0) + 1, last: Date.now() };
    localStorage.setItem(USE_KEY, JSON.stringify(use));
  } catch {
    /* storage unavailable — ranking just stays alphabetical */
  }
}

/**
 * Frequency, decayed by age.
 *
 * A raw count would let a burst of use from six months ago outrank what
 * someone is doing this week and never let go. Halving the weight every 30
 * days means old habits fade rather than calcify.
 */
function score(record: UseRecord | undefined): number {
  if (!record) return 0;
  const ageDays = (Date.now() - record.last) / 86_400_000;
  return record.count * Math.pow(0.5, ageDays / HALF_LIFE_DAYS);
}

export function rankByUse(commands: Command[]): Command[] {
  const use = readUse();
  // Stable: equal scores keep the authored order, so an unused palette looks
  // exactly as it was designed to.
  return commands
    .map((c, i) => ({ c, i, s: score(use[c.id]) }))
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.c);
}
