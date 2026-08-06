import { useState } from "react";
import { ApiError } from "../../api/client";
import type { ContributionMode, ContributionOverview } from "../../api/household";
import { contributionApi } from "../../api/household";
import { Check, Info, Scale } from "lucide-react";
import { Banner, Card, Select, Stack, Text } from "../../ui";

const MODE_LABELS: Record<ContributionMode, string> = {
  equal: "Split it down the middle",
  percentage: "An agreed percentage each",
  fixed: "A fixed amount each",
  income_based: "In proportion to what we earn",
};

/** Plain-language explanation shown beside the choice, because the difference
 *  between these is a conversation, not a setting. */
const MODE_BLURBS: Record<ContributionMode, string> = {
  equal: "Equal shares, whatever anyone earns.",
  percentage: "You each cover an agreed slice — 60/40, 70/30.",
  fixed: "You each put in a set amount every month.",
  income_based: "Shares follow income, so they re-balance themselves when a salary changes.",
};

const money = (minor: number, currency: string) =>
  `${currency} ${(minor / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/**
 * The shared split, and how it is actually going.
 *
 * The plan and the fairness comparison are shown together because they are
 * meaningless apart: a plan without actuals is an aspiration, and actuals
 * without a plan are a list of transfers.
 *
 * When the household has not agreed a split, this shows *that* rather than a
 * default. Presenting an equal split nobody chose as though they had is how a
 * product ends up in the middle of an argument it invented.
 */
export function ContributionCard({
  data,
  onChanged,
}: {
  data: ContributionOverview;
  onChanged: () => void;
}) {
  const { plan, fairness } = data;
  const [mode, setMode] = useState<ContributionMode>(plan.mode);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (next: ContributionMode) => {
    setMode(next);
    setSaving(true);
    setError(null);
    try {
      await contributionApi.set({ mode: next, currency: plan.currency });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not save that.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="What we each put in" accent="money">
      <Stack gap={4}>
        <div>
          <Select
            label="How we split shared costs"
            value={mode}
            disabled={saving}
            onChange={(e) => save(e.target.value as ContributionMode)}
          >
            {(Object.keys(MODE_LABELS) as ContributionMode[]).map((m) => (
              <option key={m} value={m}>
                {MODE_LABELS[m]}
              </option>
            ))}
          </Select>
          <Text tone="tertiary" size="xs">
            {MODE_BLURBS[mode]}
          </Text>
        </div>

        {/* An incomplete plan states why. It never falls back to a split
            nobody agreed to. */}
        {!plan.is_complete && (
          <Banner tone="info">
            {plan.blockers[0] ?? "This split cannot be worked out yet."}
          </Banner>
        )}

        {plan.is_complete && plan.contributions.length > 0 && (
          <>
            <div className="lf-split-bar" role="img" aria-label="Share of shared costs">
              {plan.contributions.map((c, i) => (
                <span
                  key={c.membership_id}
                  className={`lf-split-seg lf-split-seg--${i % 4}`}
                  style={{ width: `${Math.max(c.share_of_total * 100, 2)}%` }}
                  title={`${c.display_name}: ${Math.round(c.share_of_total * 100)}%`}
                />
              ))}
            </div>

            <Stack gap={3}>
              {plan.contributions.map((c) => (
                <div key={c.membership_id} className="lf-contrib-row">
                  <div>
                    <Text weight="medium">{c.display_name}</Text>
                    <Text tone="tertiary" size="xs">
                      {c.basis}
                    </Text>
                  </div>
                  <Text weight="medium" className="lf-num">
                    {money(c.amount_minor, plan.currency)}
                  </Text>
                </div>
              ))}
            </Stack>

            <Text tone="tertiary" size="xs">
              Against {money(plan.target_minor, plan.currency)} of shared costs a month.
            </Text>
          </>
        )}

        {plan.shortfall_minor > 0 && (
          <Banner tone="warning">
            {money(plan.shortfall_minor, plan.currency)} a month is unfunded.
          </Banner>
        )}

        {plan.notes.map((note) => (
          <Text key={note} tone="tertiary" size="xs">
            <Info size={13} strokeWidth={1.8} aria-hidden="true" /> {note}
          </Text>
        ))}

        {/* Fairness. A balanced household is told so explicitly rather than
            shown a blank space — and the wording never apportions blame. */}
        {plan.is_complete && (
          <div className={`lf-insight ${fairness.is_balanced ? "lf-insight--good" : ""}`}>
            <p className="lf-insight-title">
              {fairness.is_balanced ? (
                <Check size={15} strokeWidth={1.8} aria-hidden="true" />
              ) : (
                <Scale size={15} strokeWidth={1.8} aria-hidden="true" />
              )}{" "}
              {fairness.summary}
            </p>
            {!fairness.is_balanced && (
              <p className="lf-insight-body">
                {fairness.lines.map((l) => (
                  <span key={l.membership_id} className="lf-fair-line">
                    {l.display_name}: {money(l.actual_minor, plan.currency)} of{" "}
                    {money(l.expected_minor, plan.currency)}
                  </span>
                ))}
              </p>
            )}
          </div>
        )}

        {data.unattributed_income_minor > 0 && (
          <Text tone="tertiary" size="xs">
            {money(data.unattributed_income_minor, plan.currency)} of income arrives in an
            account nobody owns, so it is not counted towards either share. Set an owner to
            include it.
          </Text>
        )}

        {error && <Banner tone="danger">{error}</Banner>}
      </Stack>
    </Card>
  );
}
