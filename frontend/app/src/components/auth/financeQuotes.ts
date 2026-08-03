/** Famous quotes on money and financial management, shown on the auth screens.
 * Short, attributed, and rotated — a moment of wisdom while you sign in. */

export interface FinanceQuote {
  text: string;
  author: string;
}

export const FINANCE_QUOTES: readonly FinanceQuote[] = [
  { text: "Do not save what is left after spending, but spend what is left after saving.", author: "Warren Buffett" },
  { text: "Beware of little expenses; a small leak will sink a great ship.", author: "Benjamin Franklin" },
  { text: "An investment in knowledge pays the best interest.", author: "Benjamin Franklin" },
  { text: "It's not how much money you make, but how much money you keep.", author: "Robert Kiyosaki" },
  { text: "A budget is telling your money where to go instead of wondering where it went.", author: "Dave Ramsey" },
  { text: "The habit of saving is itself an education; it fosters every virtue.", author: "T.T. Munger" },
  { text: "Never spend your money before you have earned it.", author: "Thomas Jefferson" },
  { text: "Wealth consists not in having great possessions, but in having few wants.", author: "Epictetus" },
  { text: "The art is not in making money, but in keeping it.", author: "Proverb" },
  { text: "Compound interest is the eighth wonder of the world. He who understands it, earns it.", author: "Attributed to Albert Einstein" },
  { text: "Money looks better in the bank than on your feet.", author: "Sophia Amoruso" },
  { text: "Financial peace isn't the acquisition of stuff. It's learning to live on less than you make.", author: "Dave Ramsey" },
] as const;

/** Rotation interval on the auth panels. */
export const QUOTE_ROTATE_MS = 8000;

/** A stable "random" starting point so refreshes don't always open on quote #1. */
export function initialQuoteIndex(now: number = Date.now()): number {
  return Math.floor(now / QUOTE_ROTATE_MS) % FINANCE_QUOTES.length;
}

export function nextQuoteIndex(current: number): number {
  return (current + 1) % FINANCE_QUOTES.length;
}
