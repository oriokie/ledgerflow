import { useQuery } from "@tanstack/react-query";
import { fiApi } from "../../api/reports";
import { ApiError } from "../../api/client";
import { useAuth } from "../../lib/AuthContext";
import { formatAmount } from "../../lib/money";
import { Banner, Card, Meter, Text } from "../../ui";

/**
 * "When does work become optional?" — the question an advisor charges a
 * consultation to answer, computed from the ledger's own months.
 *
 * The headline is the middle of the return band, and the band is always shown
 * beside it: the difference between 4% and 6% real return is routinely a
 * decade, and a single confident year would be a lie of precision wearing a
 * nice font. "Never at this pace" renders as the actionable inverse — the
 * monthly saving that gets there in fifteen years — because a dead end with
 * no door is not advice.
 */
export function FinancialIndependencePanel() {
  const { activeWorkspace } = useAuth();
  const { data, error, isLoading } = useQuery({
    queryKey: ["fi-projection", activeWorkspace?.tenant.id],
    queryFn: () => fiApi.projection(),
    enabled: !!activeWorkspace,
    staleTime: 60_000,
    retry: false,
  });

  if (isLoading) return null;

  if (!data) {
    const detail =
      error instanceof ApiError && typeof error.detail === "string"
        ? error.detail
        : "The projection appears once there are a couple of complete months of history.";
    return (
      <Card title="Financial independence">
        <Text tone="secondary" size="sm">
          {detail}
        </Text>
      </Card>
    );
  }

  const money = (minor: number) => formatAmount(minor, data.currency);
  const middle = data.band[Math.floor(data.band.length / 2)];

  return (
    <Card title="Financial independence">
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
        {data.never_at_current_pace ? (
          <>
            <p className="lf-fi-headline">Not on the current path — but the path is priced.</p>
            <Text tone="secondary" size="sm">
              Your spending needs a pot of {money(data.fi_number_minor)} to sustain at a{" "}
              {Math.round(data.swr * 100)}% withdrawal. At your measured saving rate that number
              stays out of reach; saving{" "}
              <strong>{money(data.required_monthly_for_horizon_minor ?? 0)}/mo</strong> would reach
              it in about {data.horizon_years} years.
            </Text>
          </>
        ) : (
          <>
            <p className="lf-fi-headline">
              Work becomes optional in about {middle.years} years
              {middle.around_year ? ` — around ${middle.around_year}` : ""}.
            </p>
            <Text tone="secondary" size="sm">
              That's when a {Math.round(data.swr * 100)}% withdrawal from your projected pot covers
              your measured spending of {money(data.monthly_spending_minor)}/mo.
            </Text>
          </>
        )}

        <div>
          <Meter
            value={Math.min(100, data.progress_pct)}
            caption={`${data.progress_pct}% of your ${money(data.fi_number_minor)} number`}
            aria-label="Progress toward the financial independence number"
          />
        </div>

        <table className="lf-fi-band" aria-label="Sensitivity to the assumed return">
          <thead>
            <tr>
              {data.band.map((point) => (
                <th key={point.real_return} scope="col">
                  at {Math.round(point.real_return * 100)}% real
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {data.band.map((point) => (
                <td key={point.real_return}>
                  {point.years === null
                    ? "beyond any horizon"
                    : point.years === 0
                      ? "already there"
                      : `${point.years} yrs${point.around_year ? ` (~${point.around_year})` : ""}`}
                </td>
              ))}
            </tr>
          </tbody>
        </table>

        {data.caveats.length > 0 && (
          <Banner tone="info">
            {data.caveats.map((caveat) => (
              <Text key={caveat} tone="secondary" size="xs" style={{ display: "block" }}>
                {caveat}
              </Text>
            ))}
          </Banner>
        )}
      </div>
    </Card>
  );
}
