/**
 * Everything the landing page claims, in one file.
 *
 * Kept separate from the components for a reason that matters more here than
 * anywhere else in the product: **a marketing page is the easiest place to
 * write something that is not true.** Every claim below is one the codebase
 * actually supports, and where a claim names a capability there is a module
 * behind it. If a feature is removed, this file should fail review — which is
 * much likelier when the claims sit together than when they are scattered
 * through JSX.
 */

export interface Feature {
  /** Illustration key — see `ui/illustration`. */
  illustration: "vault" | "growth" | "insight" | "secure";
  title: string;
  body: string;
}

export const FEATURES: Feature[] = [
  {
    illustration: "vault",
    title: "A real double-entry ledger",
    body:
      "Every transaction posts balanced journal entries, the way accounting software " +
      "does it — not a list of numbers that can quietly drift out of step. You can " +
      "reconcile, and the audit trail is immutable.",
  },
  {
    illustration: "growth",
    title: "Plans you can actually check",
    body:
      "Budgets, goals, debt payoff and a day-by-day cash-flow projection. Each one " +
      "shows its working, so a figure you doubt is a figure you can verify rather " +
      "than take on faith.",
  },
  {
    illustration: "insight",
    title: "Insight that shows its evidence",
    body:
      "Spending changes, subscription detection and anomalies — each with the " +
      "reasoning attached. Nothing is asserted without the numbers it came from.",
  },
  {
    illustration: "secure",
    title: "Yours to leave with",
    body:
      "Export everything, on every plan including the free one. Reconciliation, the " +
      "audit trail and two-factor authentication are never behind a paywall.",
  },
];

/** Answers checked against the product, not aspirations. */
export const FAQ: { q: string; a: string }[] = [
  {
    q: "Do you connect to my bank?",
    a:
      "Not automatically. You import statements as CSV, or add transactions by hand, " +
      "or scan a receipt. That is a deliberate limitation rather than a missing " +
      "feature: it means there is no third party holding your banking credentials.",
  },
  {
    q: "Is the AI required?",
    a:
      "No. Every insight has a deterministic fallback, and the product ships fully " +
      "functional with no AI provider configured at all. When one is configured it " +
      "receives a summary — it cannot reach your ledger and it cannot write to it.",
  },
  {
    q: "What happens to my data if I stop paying?",
    a:
      "You keep it and you can export it. Data export, reconciliation and the audit " +
      "trail are on every tier including Free, because charging for the ability to " +
      "verify your own books — or to leave — would be indefensible.",
  },
  {
    q: "Can I use more than one currency?",
    a:
      "Yes. Accounts are held in their own currency and never silently summed. Where " +
      "a total spans currencies the product says so rather than adding them together " +
      "with an invented rate.",
  },
  {
    q: "Is the free plan a trial?",
    a:
      "No. One person, three accounts, real double-entry, budgets and your full " +
      "transaction history, with no time limit. The paid tiers add scale and the " +
      "planning tools, not the ability to keep books.",
  },
  {
    q: "Can I share a workspace?",
    a:
      "Yes, from the Family tier up, with roles and permissions. Each workspace is " +
      "isolated at the database level, not just in the interface.",
  },
];

/**
 * Customer quotes.
 *
 * **These are written samples, not real endorsements**, and the page says so
 * on screen while `sample: true` is set on them. That flag is the whole
 * mechanism: the section renders the design properly, the copy is there to be
 * adapted, and nobody visiting can mistake written examples for things real
 * customers said. Replace the quotes with attributable ones and drop the flag,
 * and the notice disappears on its own.
 *
 * The alternative — invented names presented as genuine customers — would put
 * fake endorsements on the one page whose entire argument is that this product
 * tells you the truth about your money. That trade is not worth making for a
 * landing page.
 *
 * The copy deliberately echoes what the product actually does (showing its
 * working, refusing to invent figures, free tier that is not a trial) so it
 * stays useful as a starting point rather than generic praise.
 */
export interface Testimonial {
  quote: string;
  /** Who is speaking. Kept to a role until a real person is credited. */
  attribution: string;
  /** True while this is written copy rather than something a customer said. */
  sample?: boolean;
}

export const TESTIMONIALS: Testimonial[] = [
  {
    quote:
      "I moved over from a spreadsheet I'd kept for six years. The thing that " +
      "sold me was the cash-flow view telling me it was only counting scheduled " +
      "bills — it was the first budgeting app that admitted what it didn't know.",
    attribution: "Freelance designer, two currencies",
    sample: true,
  },
  {
    quote:
      "We share a workspace for the house. Being able to see who changed a " +
      "category, and when, ended an argument we'd been having for months.",
    attribution: "Shared household, four accounts",
    sample: true,
  },
  {
    quote:
      "The debt planner showed me the payoff order and the interest I'd save, " +
      "and then showed me the arithmetic. I checked it against my own sheet " +
      "and it matched to the cent.",
    attribution: "Paying down two cards",
    sample: true,
  },
];
