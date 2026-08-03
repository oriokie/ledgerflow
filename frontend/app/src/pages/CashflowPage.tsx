import { AlertTriangle, CalendarClock, CalendarDays, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useCashflowCalendar } from "../hooks/useFinance";
import { formatAmount } from "../lib/money";
import {
  Banner,
  Card,
  EmptyState,
  Figure,
  FigureRow,
  Inline,
  PageHeader,
  SegmentedControl,
  SkeletonCard,
  Text,
} from "../ui";
import { CashflowCalendar, CashflowOutlook } from "./cashflow";
import { hasScheduledActivity, parseDay } from "./cashflow/calendarUtils";

/**
 * Projection windows.
 *
 * The old ceiling of 90 days was a UI limit, not a modelling one — the backend
 * has always projected up to a year (MAX_HORIZON_DAYS = 365). What actually
 * breaks past a quarter is the day grid, so the longer windows change which
 * view opens rather than being refused.
 */
const WINDOWS = [
  { value: "35", label: "5 weeks" },
  { value: "60", label: "2 months" },
  { value: "90", label: "3 months" },
  { value: "180", label: "6 months" },
  { value: "365", label: "12 months" },
];

/** Past this, a day-by-day grid is a wall of numbers rather than an answer. */
const GRID_LIMIT_DAYS = 90;

type ViewMode = "calendar" | "outlook";

const VIEWS: { value: ViewMode; label: string }[] = [
  { value: "calendar", label: "Calendar" },
  { value: "outlook", label: "Outlook" },
];

function shortDate(iso: string): string {
  return parseDay(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * The full-page cash flow calendar.
 *
 * The dashboard carries a fixed 5-week view for the "can I make it to payday?"
 * question; this page exists for the longer look. It leads with the trough
 * rather than the closing balance, because the closing figure answers a
 * question nobody asks — what matters is whether you survive the middle.
 */
/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline. */
export function CashflowPage({ embedded }: { embedded?: boolean } = {}) {
  const [window, setWindow] = useState("60");
  const days = Number(window);
  const { data: calendar, isLoading } = useCashflowCalendar({ days });

  const scheduled = hasScheduledActivity(calendar?.days);
  const isLongHorizon = days > GRID_LIMIT_DAYS;
  const [view, setView] = useState<ViewMode>("calendar");

  // A twelve-month grid isn't a view anyone wants to land on, so long windows
  // open on the outlook. The calendar stays reachable — it pages by month, so
  // it still works — but it stops being the default once it stops being useful.
  useEffect(() => {
    setView(isLongHorizon ? "outlook" : "calendar");
  }, [isLongHorizon]);

  const stats = useMemo(() => {
    if (!calendar) return null;
    const c = calendar.currency;
    return {
      opening: formatAmount(calendar.opening_balance_minor, c),
      closing: formatAmount(calendar.closing_balance_minor, c),
      lowest: formatAmount(calendar.lowest_balance_minor, c),
      lowestOn: calendar.lowest_balance_on ? shortDate(calendar.lowest_balance_on) : undefined,
      negativeDays: calendar.negative_day_count,
      firstNegative: calendar.first_negative_on ? shortDate(calendar.first_negative_on) : null,
      isTight: calendar.lowest_balance_minor < 0,
    };
  }, [calendar]);

  return (
    <>
      {!embedded && (
        <PageHeader
          title="Cash flow"
          eyebrow={calendar ? `Projected in ${calendar.currency}` : undefined}
          description="What your balance is expected to do, day by day, based on your scheduled income and bills."
          actions={
            <Inline gap={2}>
              {calendar && scheduled && (
                <SegmentedControl<ViewMode>
                  legend="View"
                  options={VIEWS}
                  value={view}
                  onChange={setView}
                />
              )}
              <SegmentedControl
                legend="Projection window"
                options={WINDOWS}
                value={window}
                onChange={setWindow}
              />
            </Inline>
          }
        />
      )}

      {isLoading && <SkeletonCard />}

      {!isLoading && !calendar && (
        <Card>
          <EmptyState
            icon={CalendarDays}
            illustration="no-data"
            title="Nothing to project yet"
            body="The calendar projects forward from your account balances and anything you've scheduled."
            tips={[
              "Add a checking or savings account to give the projection a starting balance.",
              "Set up recurring income so the calendar knows when you get paid.",
              "Add your bills and the calendar will warn you before the balance runs thin.",
            ]}
          />
        </Card>
      )}

      {calendar && stats && (
        <>
          {/* Answers the question the page exists for before the user has to
              read a single cell. */}
          <Card>
            {/* The trough leads: the closing balance answers a question nobody
                asks, and what matters is whether you survive the middle. These
                four were duplicated inside the calendar below in different
                typography — one row now, and the calendar carries none. */}
            <FigureRow lead>
              <Figure
                label="Lowest point"
                size="hero"
                amountMinor={calendar.lowest_balance_minor}
                currency={calendar.currency}
                neutral
                certainty="projected"
                hint={stats.lowestOn ? `on ${stats.lowestOn}` : undefined}
                tone={stats.isTight ? "critical" : "default"}
              />
              <Figure
                label="Starting balance"
                amountMinor={calendar.opening_balance_minor}
                currency={calendar.currency}
                neutral
              />
              <Figure
                label="Ends at"
                amountMinor={calendar.closing_balance_minor}
                currency={calendar.currency}
                neutral
                certainty="projected"
              />
              <Figure
                label="Days below zero"
                value={String(stats.negativeDays)}
                hint={stats.firstNegative ? `first on ${stats.firstNegative}` : "none projected"}
                tone={stats.negativeDays > 0 ? "critical" : "default"}
              />
            </FigureRow>

            {!scheduled ? null : stats.isTight ? (
              <div className="lf-cashflow-verdict" data-tone="danger">
                <AlertTriangle size={16} aria-hidden="true" />
                <Text size="sm">
                  This projection dips below zero. Moving a bill, or holding back a transfer, would
                  change the outcome.
                </Text>
              </div>
            ) : (
              <div className="lf-cashflow-verdict">
                <ShieldCheck size={16} aria-hidden="true" />
                <Text size="sm" tone="secondary">
                  Your balance stays above zero across this whole window, bottoming out at{" "}
                  {stats.lowest}
                  {stats.lowestOn ? ` on ${stats.lowestOn}` : ""}.
                </Text>
              </div>
            )}
          </Card>

          <div className="lf-dash-section">
            <Card>
              {/* A calendar renders only when the days differ. Sixty identical
                  cells is the absence of a forecast, not a forecast — and the
                  grid was the only thing on the page that never said so. */}
              {/* "Nothing scheduled" stopped being the same thing as "nothing
                  to project" when the everyday-spending band landed. With no
                  bills but real history, the balance is emphatically *not*
                  flat — on the demo workspace it falls by over KES 7,000 across
                  90 days — and saying it is would be a false claim the product
                  can already disprove from its own data. */}
              {!scheduled && !calendar.everyday ? (
                <EmptyState
                  icon={CalendarClock}
                  title="Nothing scheduled"
                  body={`Your balance is flat at ${stats.closing} across this window because no bills or recurring income are set up yet, and there isn't enough spending history yet to estimate the rest. Add them and this becomes a real projection.`}
                  action={
                    <Inline gap={2}>
                      <Link className="lf-btn lf-btn--primary lf-btn--sm" to="/bills">
                        Add a bill
                      </Link>
                      <Link className="lf-btn lf-btn--secondary lf-btn--sm" to="/recurring">
                        Detect from history
                      </Link>
                    </Inline>
                  }
                />
              ) : view === "outlook" || !scheduled ? (
                <>
                  {!scheduled && (
                    <Banner tone="info">
                      Nothing is scheduled yet, so this projection is your day-to-day spending
                      alone. Adding bills and recurring income will sharpen it.
                    </Banner>
                  )}
                  <CashflowOutlook calendar={calendar} />
                </>
              ) : (
                <CashflowCalendar calendar={calendar} />
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
