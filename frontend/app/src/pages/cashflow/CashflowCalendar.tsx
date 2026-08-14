import { AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";
import { Fragment, useMemo, useRef, useState } from "react";
import type { CashflowCalendar as Calendar, CashflowCalendarDay } from "../../api/types";
import { formatAmountSigned } from "../../lib/money";
import { Button, Money, SegmentedControl, Text } from "../../ui";
import { CashflowDayDetail } from "./CashflowDayDetail";
import {
  dayTone,
  isSameDay,
  monthHeadingForWeek,
  formatFullDate,
  parseDay,
  SOURCE_ICONS,
  toWeekGrid,
  weekdayLabels,
  type CalendarView,
} from "./calendarUtils";

const VIEW_OPTIONS: { value: CalendarView; label: string }[] = [
  { value: "month", label: "Month" },
  { value: "week", label: "Week" },
  { value: "timeline", label: "Timeline" },
];

/** Arrow-key steps for the day grid's roving tabindex, in cells-per-week
 * terms: Left/Right move one day, Up/Down move a full row (7 days) to land
 * on the same weekday. */
const ARROW_STEPS: Record<string, number> = {
  ArrowRight: 1,
  ArrowLeft: -1,
  ArrowDown: 7,
  ArrowUp: -7,
};

/** Compact day/month label, e.g. "25 Jul". */
function shortDate(iso: string, locale?: string): string {
  return parseDay(iso).toLocaleDateString(locale, { day: "numeric", month: "short" });
}

function DayCell({
  day,
  openingBalanceMinor,
  currency,
  today,
  selected,
  onSelect,
  isActive,
  onCellKeyDown,
  onCellFocus,
  registerCellRef,
}: {
  day: CashflowCalendarDay | null;
  openingBalanceMinor: number;
  currency: string;
  today: Date;
  selected: string | null;
  onSelect: (iso: string) => void;
  /** Whether this is the grid's one roving-tabindex stop. */
  isActive: boolean;
  onCellKeyDown: (e: React.KeyboardEvent<HTMLButtonElement>, iso: string) => void;
  onCellFocus: (iso: string) => void;
  registerCellRef: (iso: string, el: HTMLButtonElement | null) => void;
}) {
  // A blank pad cell, not a day with a zero balance — the two must never be
  // confusable, so it renders as inert markup with no figures at all.
  if (day === null) {
    return (
      <div role="gridcell" className="lf-cal-cell lf-cal-cell--blank" aria-hidden="true" />
    );
  }

  const date = parseDay(day.day);
  const tone = dayTone(day, openingBalanceMinor);
  const isToday = isSameDay(date, today);

  // The button is wrapped rather than given role="gridcell" itself: overriding
  // the role would strip its button semantics, and a date grid whose cells no
  // longer announce as pressable is a worse outcome than the lint it silences.
  // `display: contents` on the wrapper keeps the existing grid tracks intact.
  return (
    <div role="gridcell" className="lf-cal-cellwrap">
    <button
      ref={(el) => registerCellRef(day.day, el)}
      type="button"
      className="lf-cal-cell"
      data-tone={tone}
      data-today={isToday || undefined}
      aria-current={isToday ? "date" : undefined}
      aria-pressed={selected === day.day}
      // Roving tabindex: the ARIA grid pattern expects a single Tab stop for
      // the whole grid, with arrow keys moving *within* it — not one Tab stop
      // per cell, which made a 90-day window ~90 stops deep.
      tabIndex={isActive ? 0 : -1}
      onKeyDown={(e) => onCellKeyDown(e, day.day)}
      onFocus={() => onCellFocus(day.day)}
      onClick={() => onSelect(day.day)}
      // Screen readers get the full picture; the visual cell stays terse.
      aria-label={`${date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}. Projected balance ${formatAmountSigned(day.closing_minor, currency)}.${
        day.is_negative ? " Predicted overdraft." : ""
      }${day.events.length ? ` ${day.events.length} expected movements.` : ""}`}
    >
      <span className="lf-cal-daynum">{date.getDate()}</span>

      {day.events.length > 0 && (
        <span className="lf-cal-dots" aria-hidden="true">
          {day.events.slice(0, 3).map((e, i) => {
            const Icon = SOURCE_ICONS[e.source];
            return <Icon key={i} size={11} strokeWidth={2.2} data-in={e.amount_minor > 0 || undefined} />;
          })}
          {day.events.length > 3 && <span className="lf-cal-more">+{day.events.length - 3}</span>}
        </span>
      )}

      <span className="lf-cal-balance" aria-hidden="true">
        {formatAmountSigned(day.closing_minor, currency)}
      </span>

      {day.is_negative && (
        <AlertTriangle className="lf-cal-warn" size={11} strokeWidth={2.4} aria-hidden="true" />
      )}
    </button>
    </div>
  );
}

/**
 * The cash flow calendar.
 *
 * Answers the question a monthly summary cannot: *will I go negative before
 * payday, and on which day?* Every cell shows the projected **closing** balance
 * rather than the day's net movement, because the running balance is what
 * determines whether a payment clears.
 *
 * Colour encodes severity and icons encode the kind of movement, so the two
 * channels never carry the same information twice — and neither is the sole
 * carrier: every cell has a text balance and a full screen-reader label.
 */
export function CashflowCalendar({ calendar }: { calendar: Calendar }) {
  const [view, setView] = useState<CalendarView>("month");
  const [weekOffset, setWeekOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  // The grid's roving-tabindex position — the one cell that is a Tab stop.
  // Kept as the day's ISO string rather than a [week, day] index pair so it
  // survives view switches and week paging without translation.
  const [activeDay, setActiveDay] = useState<string | null>(null);
  const cellRefs = useRef(new Map<string, HTMLButtonElement>());

  const today = useMemo(() => new Date(), []);
  const labels = useMemo(() => weekdayLabels(), []);
  const weeks = useMemo(() => toWeekGrid(calendar.days), [calendar.days]);

  const selectedDay = useMemo(
    () => calendar.days.find((d) => d.day === selected) ?? null,
    [calendar.days, selected],
  );

  const visibleWeeks = view === "week" ? weeks.slice(weekOffset, weekOffset + 1) : weeks;
  const daysWithEvents = useMemo(() => calendar.days.filter((d) => d.events.length > 0), [calendar.days]);

  // Falls back to today's cell (or the first real cell) whenever the
  // previously-active day has scrolled out of view — a view switch or a week
  // page can both do that, and the grid must always have exactly one stop.
  const defaultActiveDay = useMemo(() => {
    const realDays = visibleWeeks.flat().filter((d): d is CashflowCalendarDay => d !== null);
    return realDays.find((d) => isSameDay(parseDay(d.day), today))?.day ?? realDays[0]?.day ?? null;
  }, [visibleWeeks, today]);

  const activeIso =
    activeDay && visibleWeeks.some((week) => week.some((d) => d?.day === activeDay))
      ? activeDay
      : defaultActiveDay;

  function registerCellRef(iso: string, el: HTMLButtonElement | null) {
    if (el) cellRefs.current.set(iso, el);
    else cellRefs.current.delete(iso);
  }

  // Selecting a cell (click, or Enter/Space on the focused one) also claims
  // the roving-tabindex slot — otherwise a click in Safari, which doesn't
  // focus <button>s itself, would leave Tab order pointing at a stale cell.
  function handleSelect(iso: string) {
    setSelected(iso);
    setActiveDay(iso);
  }

  // Moves both DOM focus and the roving tabindex to the next real cell in
  // `direction` steps of `step`, skipping blank pad cells rather than
  // stopping on them — a blank cell isn't a day, so it isn't a stop.
  function moveFocus(fromIso: string, step: number) {
    const cells = visibleWeeks.flat();
    const from = cells.findIndex((d) => d?.day === fromIso);
    if (from === -1) return;
    for (let i = from + step; i >= 0 && i < cells.length; i += step) {
      const candidate = cells[i];
      if (candidate) {
        setActiveDay(candidate.day);
        cellRefs.current.get(candidate.day)?.focus();
        return;
      }
    }
  }

  function handleCellKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, iso: string) {
    const step = ARROW_STEPS[e.key];
    if (step === undefined) return;
    e.preventDefault();
    moveFocus(iso, step);
  }

  return (
    <section className="lf-cal" aria-label="Cash flow calendar">
      <header className="lf-cal-head">
        {/* The low point and the closing balance were stated here *and* in the
            page's summary card 200px above, in different typography — the same
            two numbers, twice, disagreeing about how important they are. The
            page owns them now; the calendar draws the days. This also removed
            the non-wrapping flex row that pushed the whole document sideways
            at 375px. */}
        <SegmentedControl<CalendarView>
          legend="Calendar view"
          options={VIEW_OPTIONS}
          value={view}
          onChange={(v) => {
            setView(v);
            // A view change resets paging: staying on "week 4" after switching
            // to month and back is disorienting.
            setWeekOffset(0);
          }}
        />
      </header>

      {/* The single most actionable line the calendar produces. */}
      {calendar.first_negative_on && (
        <p className="lf-cal-alert" role="status">
          <AlertTriangle size={15} strokeWidth={2} aria-hidden="true" />
          <span>
            Projected to go below zero on <strong>{formatFullDate(calendar.first_negative_on)}</strong>
            {calendar.negative_day_count > 1 && ` and ${calendar.negative_day_count - 1} other days`}.
          </span>
        </p>
      )}

      {view === "timeline" ? (
        <ol className="lf-cal-timeline">
          {daysWithEvents.length === 0 && (
            <li className="lf-cal-timeline-empty">
              <Text tone="tertiary" size="sm">
                Nothing scheduled in this window.
              </Text>
            </li>
          )}
          {daysWithEvents.map((day) => (
            <li key={day.day}>
              <button
                type="button"
                className="lf-cal-timeline-row"
                data-tone={dayTone(day, calendar.opening_balance_minor)}
                onClick={() => setSelected(day.day)}
                aria-pressed={selected === day.day}
              >
                <span className="lf-cal-timeline-date">{shortDate(day.day)}</span>
                <span className="lf-cal-timeline-events">
                  {day.events.map((e, i) => (
                    <span key={i} className="lf-cal-timeline-event">
                      {e.description}
                    </span>
                  ))}
                </span>
                <span className="lf-cal-timeline-balance">
                  <Money amountMinor={day.closing_minor} currency={calendar.currency} neutral />
                </span>
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <>
          {view === "week" && (
            <div className="lf-cal-weeknav">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setWeekOffset((w) => Math.max(0, w - 1))}
                disabled={weekOffset === 0}
                icon={<ChevronLeft size={15} aria-hidden="true" />}
              >
                Previous
              </Button>
              <Text as="span" tone="secondary" size="sm">
                Week {weekOffset + 1} of {weeks.length}
              </Text>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setWeekOffset((w) => Math.min(weeks.length - 1, w + 1))}
                disabled={weekOffset >= weeks.length - 1}
              >
                Next
                <ChevronRight size={15} aria-hidden="true" />
              </Button>
            </div>
          )}

          <div className="lf-cal-grid" role="grid" aria-label="Projected daily balances">
            <div className="lf-cal-weekdays" role="row">
              {labels.map((l) => (
                <span key={l} role="columnheader">
                  {l}
                </span>
              ))}
            </div>
            {visibleWeeks.map((week, vi) => {
              // In week view, `visibleWeeks` is a one-week slice — index into
              // the full `weeks` array so the heading still sees the real
              // previous week, not `undefined`, when paging mid-month.
              const wi = view === "week" ? weekOffset + vi : vi;
              const heading = monthHeadingForWeek(week, weeks[wi - 1]);
              return (
                <Fragment key={wi}>
                  {heading && (
                    <div className="lf-cal-monthrow" role="row">
                      <span role="columnheader" aria-colspan={7} className="lf-cal-monthheading">
                        {heading}
                      </span>
                    </div>
                  )}
                  <div className="lf-cal-week" role="row">
                    {week.map((day, di) => (
                      <DayCell
                        key={day?.day ?? `blank-${wi}-${di}`}
                        day={day}
                        openingBalanceMinor={calendar.opening_balance_minor}
                        currency={calendar.currency}
                        today={today}
                        selected={selected}
                        onSelect={handleSelect}
                        isActive={day !== null && day.day === activeIso}
                        onCellKeyDown={handleCellKeyDown}
                        onCellFocus={setActiveDay}
                        registerCellRef={registerCellRef}
                      />
                    ))}
                  </div>
                </Fragment>
              );
            })}
          </div>
        </>
      )}

      {selectedDay && (
        <CashflowDayDetail
          day={selectedDay}
          currency={calendar.currency}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}
