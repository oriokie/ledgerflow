import { formatAmount } from "../../lib/money";

const R = 52;
const STROKE = 12;
const CIRC = 2 * Math.PI * R;

/**
 * A circular progress ring — the centrepiece motivator. The arc fills clockwise
 * from the top, small ticks mark the 25/50/75% checkpoints, and the whole ring
 * turns green on completion.
 */
export function GoalProgressRing({
  percent,
  met,
  savedMinor,
  currency,
}: {
  percent: number;
  met: boolean;
  savedMinor: number;
  currency: string;
}) {
  const pct = Math.max(0, Math.min(100, percent));
  const offset = CIRC * (1 - pct / 100);
  return (
    <div className={`lf-goal-ring${met ? " lf-goal-ring--met" : ""}`}>
      <svg viewBox="0 0 120 120" role="img" aria-label={`${Math.round(percent)}% saved`}>
        <circle className="lf-goal-ring-track" cx="60" cy="60" r={R} strokeWidth={STROKE} />
        <circle
          className="lf-goal-ring-arc"
          cx="60"
          cy="60"
          r={R}
          strokeWidth={STROKE}
          strokeDasharray={CIRC}
          strokeDashoffset={offset}
          transform="rotate(-90 60 60)"
        />
        {[25, 50, 75].map((p) => (
          <line
            key={p}
            className="lf-goal-ring-tick"
            x1="60"
            y1="2"
            x2="60"
            y2="14"
            transform={`rotate(${(p / 100) * 360} 60 60)`}
          />
        ))}
      </svg>
      <div className="lf-goal-ring-center">
        <span className="lf-goal-ring-pct">{Math.round(percent)}%</span>
        <span className="lf-goal-ring-sub">{formatAmount(savedMinor, currency)}</span>
      </div>
    </div>
  );
}
