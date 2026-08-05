import { useEffect, useState } from "react";
import { FINANCE_QUOTES, QUOTE_ROTATE_MS, initialQuoteIndex, nextQuoteIndex } from "./financeQuotes";

/**
 * A rotating famous quote on financial management. Crossfades between quotes
 * every few seconds (motion is CSS-driven, so prefers-reduced-motion turns the
 * fade off globally while the text still updates). Marked aria-hidden — it's
 * ambience, and announcing a new quote every 8s would spam screen readers.
 */
export function QuoteRotator() {
  const [index, setIndex] = useState(() => initialQuoteIndex());
  const [entering, setEntering] = useState(true);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setEntering(false);
      // Give the outgoing quote a beat to fade before swapping the text in.
      window.setTimeout(() => {
        setIndex((i) => nextQuoteIndex(i));
        setEntering(true);
      }, 240);
    }, QUOTE_ROTATE_MS);
    return () => window.clearInterval(timer);
  }, []);

  const quote = FINANCE_QUOTES[index];
  return (
    <figure className="lf-quote" data-entering={entering} aria-hidden="true">
      {/* Position dots. The reference layout has carousel dots under its
          illustration; here they mark where the rotation actually is, so they
          report something true rather than being decoration shaped like a
          control. Not interactive — there is nothing to click, and a dot that
          looks pressable but isn't is worse than no dot. */}
      <div className="lf-quote-dots">
        {FINANCE_QUOTES.map((q, i) => (
          <span key={q.author + i} className="lf-quote-dot" data-active={i === index} />
        ))}
      </div>
      <blockquote className="lf-quote-text">&ldquo;{quote.text}&rdquo;</blockquote>
      <figcaption className="lf-quote-author">&mdash; {quote.author}</figcaption>
    </figure>
  );
}
