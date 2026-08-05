import { CalendarClock } from "lucide-react";
import { Link } from "react-router-dom";
import type { Bill } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Card, EmptyState } from "../../ui";

function daysUntil(bill: Bill): number {
  if (typeof bill.days_until_due === "number") return bill.days_until_due;
  const due = new Date(bill.due_on).getTime();
  if (Number.isNaN(due)) return 0;
  return Math.ceil((due - Date.now()) / 86_400_000);
}

function DuePill({ bill }: { bill: Bill }) {
  if (bill.status === "overdue") return <span className="lf-due-pill lf-due-pill--overdue">Overdue</span>;
  const d = daysUntil(bill);
  const label = d <= 0 ? "Due today" : d === 1 ? "Tomorrow" : `In ${d} days`;
  const cls = d <= 3 ? "lf-due-pill lf-due-pill--soon" : "lf-due-pill";
  return <span className={cls}>{label}</span>;
}

export function UpcomingBills({ bills, currency }: { bills: Bill[] | undefined; currency: string }) {
  const upcoming = (bills ?? [])
    .filter((b) => b.status === "upcoming" || b.status === "overdue")
    .slice()
    .sort((a, b) => new Date(a.due_on).getTime() - new Date(b.due_on).getTime())
    .slice(0, 5);

  return (
    <Card
      accent="plan"
      title="Upcoming bills"
      action={
        <Link to="/bills" className="lf-section-link">
          All bills
        </Link>
      }
    >
      {upcoming.length === 0 ? (
        <EmptyState icon={CalendarClock} title="Nothing due" body="You have no upcoming bills." />
      ) : (
        <div className="lf-row-list">
          {upcoming.map((b) => (
            <div key={b.id} className="lf-row-item">
              <div className="lf-row-main">
                <div className="lf-row-title">{b.name}</div>
                <div className="lf-row-sub">
                  <DuePill bill={b} />
                </div>
              </div>
              <div className="lf-row-right">{formatAmount(b.amount_minor, b.currency || currency)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
