import { AlertTriangle } from "lucide-react";
import type { CashflowCalendarDay } from "../../api/types";
import { Modal, Money, Text } from "../../ui";
import { parseDay, SOURCE_ICONS, SOURCE_LABELS } from "./calendarUtils";

/**
 * A single projected day, opened by clicking a cell.
 *
 * Leads with the running balance rather than the day's net movement: what
 * matters is whether a payment clears, and that depends on the balance the day
 * inherits, not on what happens to move that morning.
 */
export function CashflowDayDetail({
  day,
  currency,
  onClose,
}: {
  day: CashflowCalendarDay;
  currency: string;
  onClose: () => void;
}) {
  const date = parseDay(day.day);

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={date.toLocaleDateString(undefined, {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      })}
      description="Projected from today's balance and everything scheduled between now and then."
    >
      <div className="lf-cal-detail">
        <dl className="lf-cal-detail-balances">
          <div>
            <dt>Opening</dt>
            <dd>
              <Money amountMinor={day.opening_minor} currency={currency} neutral />
            </dd>
          </div>
          <div>
            <dt>Money in</dt>
            <dd>
              <Money amountMinor={day.inflow_minor} currency={currency} neutral />
            </dd>
          </div>
          <div>
            <dt>Money out</dt>
            <dd>
              <Money amountMinor={day.outflow_minor} currency={currency} neutral />
            </dd>
          </div>
          <div>
            <dt>Closing</dt>
            <dd data-negative={day.is_negative || undefined}>
              <Money amountMinor={day.closing_minor} currency={currency} neutral />
            </dd>
          </div>
        </dl>

        {day.is_negative && (
          <p className="lf-cal-alert" role="status">
            <AlertTriangle size={15} strokeWidth={2} aria-hidden="true" />
            <span>
              This day is projected to close below zero. Moving money in before then, or delaying a
              payment, would avoid an overdraft.
            </span>
          </p>
        )}

        {day.events.length === 0 ? (
          <Text tone="tertiary" size="sm">
            Nothing scheduled on this day — the balance simply carries forward.
          </Text>
        ) : (
          <ul className="lf-cal-detail-events">
            {day.events.map((event, i) => {
              const Icon = SOURCE_ICONS[event.source];
              const incoming = event.amount_minor > 0;
              return (
                <li key={i} className="lf-cal-detail-event">
                  <span className="lf-cal-detail-icon" data-in={incoming || undefined} aria-hidden="true">
                    <Icon size={15} strokeWidth={1.9} />
                  </span>
                  <span className="lf-cal-detail-main">
                    <span className="lf-cal-detail-name">{event.description}</span>
                    <span className="lf-cal-detail-meta">
                      {SOURCE_LABELS[event.source]}
                      {event.account_name && ` · ${event.account_name}`}
                      {event.category_name && ` · ${event.category_name}`}
                      {event.is_overdue && " · overdue"}
                    </span>
                  </span>
                  <Money amountMinor={event.amount_minor} currency={currency} />
                </li>
              );
            })}
          </ul>
        )}

        <Text tone="tertiary" size="xs">
          Projections come from recurring transactions and unpaid bills. Anything you haven't scheduled
          won't appear here.
        </Text>
      </div>
    </Modal>
  );
}
