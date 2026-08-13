import clsx from "clsx";
import { amountDirectionClass, formatAmountParts } from "../lib/money";
import { useFitFontSize } from "../lib/useFitFontSize";

interface MoneyProps {
  amountMinor: number;
  currency: string;
  /** Transfers use the muted "moving your own money" treatment instead of in/out. */
  isTransfer?: boolean;
  /** Large hero figure (safe-to-spend, dashboard headline numbers). */
  hero?: boolean;
  /** Suppress the in/out colour coding — for neutral contexts like totals.
   *
   * Colour only. The minus sign is *not* suppressed: colour and sign are
   * different channels, and dropping the sign would render a −$450 deficit as
   * a comfortable "$450" wherever a total can legitimately go negative. */
  neutral?: boolean;
  className?: string;
}

/**
 * Renders the design system's signature amount treatment: large integer part,
 * small decimal cents, colored by direction. Money-in is verdant (a
 * highlighted event); money-out is plain ink (normal life, not an error);
 * transfers are muted — this mirrors the semantics documented in tokens.css.
 */
export function Money({ amountMinor, currency, isTransfer, hero, neutral, className }: MoneyProps) {
  const { whole, cents } = formatAmountParts(amountMinor, currency);
  // Always signed. `neutral` governs colour, never whether the number is
  // truthful about its direction.
  const sign = amountMinor < 0 ? "\u2212" : "";
  // A no-op unless `hero` \u2014 no ResizeObserver overhead on ordinary table/inline
  // amounts, which is the overwhelming majority of renders.
  const fitRef = useFitFontSize<HTMLDataElement>(!!hero, [amountMinor, currency]);
  return (
    <data
      ref={hero ? fitRef : undefined}
      className={clsx(
        "lf-amount",
        !neutral && amountDirectionClass(amountMinor, !!isTransfer),
        hero && "lf-amount--hero lf-display",
        className,
      )}
      value={(amountMinor / 100).toFixed(2)}
    >
      {sign}
      {whole}
      <span className="lf-amount-cents">{cents}</span>
    </data>
  );
}
