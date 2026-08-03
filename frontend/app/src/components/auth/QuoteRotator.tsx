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
      <blockquote className="lf-quote-text">&ldquo;{quote.text}&rdquo;</blockquote>
      <figcaption className="lf-quote-author">&mdash; {quote.author}</figcaption>
    </figure>
  );
}
