import { Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { activityApi, approvalApi, contributionApi } from "../api/household";
import type { ActivityEvent, ContributionOverview, SpendApproval } from "../api/household";
import { ActivityCard } from "./household/ActivityCard";
import { ApprovalsCard } from "./household/ApprovalsCard";
import { ContributionCard } from "./household/ContributionCard";
import type {
  ChangeRequest,
  Dependant,
  HouseholdSummary,
  SharingPolicy,
} from "../api/household";
import { changeRequestApi, householdApi } from "../api/household";
import { formatAmount } from "../lib/money";
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Figure,
  FormField,
  Grid,
  Input,
  PageHeader,
  Select,
  SkeletonCard,
  Stack,
  Text,
} from "../ui";

const POLICY_LABEL: Record<SharingPolicy, string> = {
  private: "Only me",
  shared: "Shared",
  read_only: "They can see, only I change",
  approval_required: "Changes need my approval",
};

function Withheld({ count }: { count: number }) {
  if (!count) return null;
  return (
    <Banner tone="info">
      <Text size="sm">
        {count} account{count === 1 ? "" : "s"} in this household {count === 1 ? "is" : "are"}{" "}
        private to whoever owns {count === 1 ? "it" : "them"}. The totals above count{" "}
        {count === 1 ? "it" : "them"}; the breakdown below does not, so the two will not
        reconcile — that is the privacy working, not a mistake.
      </Text>
    </Banner>
  );
}

function Members({ summary }: { summary: HouseholdSummary }) {
  const { members } = summary.position;
  return (
    <Card title="Who is in this household">
      <ul className="lf-finding-list">
        {members.map((m) => (
          <li key={m.membership_id}>
            <div className="lf-risk-row">
              <Text size="sm" weight="medium">
                {m.display_name} {m.is_you && <Badge tone="neutral">you</Badge>}
              </Text>
              <Text size="sm" tone="secondary">
                {m.contribution_share === null
                  ? "no agreed share"
                  : `${Math.round(m.contribution_share * 100)}% of shared costs`}
              </Text>
            </div>
            <Text size="sm" tone="secondary">
              {m.relationship} · {m.visible_account_count} account
              {m.visible_account_count === 1 ? "" : "s"} you can see
            </Text>
          </li>
        ))}
      </ul>
      {summary.position.notes.map((n) => (
        <Text key={n} size="xs" tone="tertiary">
          {n}
        </Text>
      ))}
    </Card>
  );
}

function Dependants({ items, onChanged }: { items: Dependant[]; onChanged: () => void }) {
  const [name, setName] = useState("");
  const [relationship, setRelationship] = useState("child");
  const [cost, setCost] = useState("");
  const [until, setUntil] = useState("");

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    await householdApi.addDependant({
      name: name.trim(),
      relationship,
      monthly_cost_minor: cost ? Math.round(Number(cost) * 100) : null,
      support_until_year: until ? Number(until) : null,
    });
    setName("");
    setCost("");
    setUntil("");
    onChanged();
  };

  return (
    <Card title="Who you support">
      {items.length > 0 && (
        <ul className="lf-finding-list">
          {items.map((d) => (
            <li key={d.id}>
              <div className="lf-risk-row">
                <Text size="sm" weight="medium">
                  {d.name}
                </Text>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    await householdApi.removeDependant(d.id);
                    onChanged();
                  }}
                >
                  Remove
                </Button>
              </div>
              <Text size="sm" tone="secondary">
                {d.relationship}
                {d.monthly_cost_minor ? ` · ${d.monthly_cost_minor / 100} a month` : " · no cost recorded"}
                {d.support_until_year ? ` · until ${d.support_until_year}` : ""}
              </Text>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="lf-scenario-form">
        <div className="lf-scenario-form-grid">
          <FormField label="Name" htmlFor="dependant-name">
            <Input id="dependant-name" value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <FormField label="Relationship" htmlFor="dependant-rel">
            <Select
              id="dependant-rel"
              value={relationship}
              onChange={(e) => setRelationship(e.target.value)}
            >
              <option value="child">Child</option>
              <option value="parent">Parent</option>
              <option value="other">Other</option>
            </Select>
          </FormField>
          <FormField
            label="Monthly cost"
            htmlFor="dependant-cost"
            hint="Left blank means not recorded — nothing is estimated"
          >
            <Input
              id="dependant-cost"
              type="number"
              step="any"
              value={cost}
              onChange={(e) => setCost(e.target.value)}
            />
          </FormField>
          <FormField label="Supported until (year)" htmlFor="dependant-until">
            <Input
              id="dependant-until"
              type="number"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </FormField>
        </div>
        <Button type="submit" disabled={!name.trim()}>
          Add
        </Button>
      </form>
    </Card>
  );
}


/**
 * The approval queue.
 *
 * Shown to the account's owner and the person who asked, and to nobody else —
 * a third member learning that one partner asked another to un-hide an account
 * would be told something that is not theirs. Declined requests stay visible:
 * the record is the point of the mechanism.
 */
function Approvals({ items, onChanged }: { items: ChangeRequest[]; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);

  const resolve = async (id: string, action: "approve" | "decline") => {
    setError(null);
    try {
      if (action === "approve") await changeRequestApi.approve(id);
      else await changeRequestApi.decline(id);
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : "Couldn't resolve that request.",
      );
    }
  };

  return (
    <Card title="Requests">
      {error && <Banner tone="danger">{error}</Banner>}
      {items.length === 0 ? (
        <Text size="sm" tone="secondary">
          Nothing waiting. When someone asks to change an account you own, it appears here —
          and approving it applies the change.
        </Text>
      ) : (
        <ul className="lf-finding-list">
          {items.map((r) => (
            <li key={r.id}>
              <div className="lf-risk-row">
                <Text size="sm" weight="medium">
                  {r.summary}
                </Text>
                <Badge
                  tone={
                    r.status === "approved"
                      ? "success"
                      : r.status === "declined"
                        ? "neutral"
                        : "warning"
                  }
                >
                  {r.status}
                </Badge>
              </div>
              {r.status === "pending" && (
                <div className="lf-event-row-actions">
                  <Button size="sm" onClick={() => resolve(r.id, "approve")}>
                    Approve
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => resolve(r.id, "decline")}>
                    Decline
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Text size="xs" tone="tertiary">
        Only the account's owner can approve — not an admin, not the workspace owner. A
        request can change an account's name or how it is shared; it can never move money.
      </Text>
    </Card>
  );
}

/**
 * The family dashboard.
 *
 * Its one unusual job is showing a total that does not reconcile with its own
 * breakdown, and saying why. Every instinct in dashboard design pushes toward
 * hiding that; doing so would mean either lying about the household's position
 * or exposing what somebody chose to keep private.
 */
export function HouseholdPage() {
  const [summary, setSummary] = useState<HouseholdSummary | null>(null);
  const [dependants, setDependants] = useState<Dependant[]>([]);
  const [requests, setRequests] = useState<ChangeRequest[]>([]);
  const [contributions, setContributions] = useState<ContributionOverview | null>(null);
  const [approvals, setApprovals] = useState<SpendApproval[]>([]);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      // Settled rather than all-or-nothing: these are independent surfaces,
      // and a household should not lose its net worth because the activity
      // feed timed out.
      const [s, d, r, c, a, ev] = await Promise.allSettled([
        householdApi.summary(),
        householdApi.dependants(),
        changeRequestApi.list(),
        contributionApi.get(),
        approvalApi.list("pending"),
        activityApi.list({ limit: 12 }),
      ]);
      if (s.status === "rejected") throw s.reason;
      setSummary(s.value);
      if (d.status === "fulfilled") setDependants(d.value.results);
      if (r.status === "fulfilled") setRequests(r.value.results);
      if (c.status === "fulfilled") setContributions(c.value);
      if (a.status === "fulfilled") setApprovals(a.value);
      if (ev.status === "fulfilled") setActivity(ev.value);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't load the household.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <>
        <PageHeader title="Household" description="Where you stand together." />
        <SkeletonCard />
      </>
    );
  }

  if (error || !summary) {
    return (
      <>
        <PageHeader title="Household" description="Where you stand together." />
        <EmptyState
          icon={Users}
          title="Nothing to show yet"
          body={error ?? "Add an account to get started."}
        />
      </>
    );
  }

  const { position, coverage, expense_split: split } = summary;
  const currency = position.currency;

  return (
    <>
      <PageHeader
        title="Household"
        description="Where you stand together — including the parts you keep to yourselves."
      />

      <Stack gap={5}>
        <Grid cols={4}>
          <Figure
            label="Household net worth"
            value={formatAmount(position.net_worth_minor, currency)}
            hint="Counts every account, including private ones"
          />
          <Figure
            label="What you can itemise"
            value={formatAmount(position.visible_assets_minor, currency)}
            hint={`${position.withheld_account_count} account(s) withheld`}
          />
          <Figure
            label="Household runway"
            value={`${coverage.household_runway_months} months`}
            hint={
              coverage.household_runway_months !== coverage.visible_runway_months
                ? `${coverage.visible_runway_months} from what you can see`
                : undefined
            }
          />
          <Figure label="People supported" value={String(position.dependants)} />
        </Grid>

        <Withheld count={position.withheld_account_count} />

        {coverage.notes.map((n) => (
          <Text key={n} size="sm" tone="secondary">
            {n}
          </Text>
        ))}

        <Grid cols={2}>
          <Members summary={summary} />
          <Dependants items={dependants} onChanged={load} />
        </Grid>

        {/* What the two of you act on, above the aggregates that give it
            context. Approvals and activity share a column because both are
            feeds; the split is the decision and gets the width. */}
        <div className="lf-household-grid">
          <Stack gap={4}>
            {contributions && <ContributionCard data={contributions} onChanged={load} />}
            <ApprovalsCard items={approvals} onChanged={load} />
          </Stack>
          <ActivityCard events={activity} />
        </div>


        <Approvals items={requests} onChanged={load} />

        <Card title="Shared costs">
          <Text size="sm" tone="secondary">
            {formatAmount(split.monthly_dependant_cost_minor, currency)} a month, split by the
            shares each of you has agreed to.
          </Text>
          <ul className="lf-finding-list">
            {split.per_member.map((m) => (
              <li key={m.membership_id}>
                <div className="lf-risk-row">
                  <Text size="sm" weight="medium">
                    {m.display_name}
                  </Text>
                  <Text size="sm" tone="secondary">
                    {m.monthly_minor === null
                      ? "no agreed share"
                      : formatAmount(m.monthly_minor, currency)}
                  </Text>
                </div>
              </li>
            ))}
          </ul>
          {split.notes.map((n) => (
            <Text key={n} size="xs" tone="tertiary">
              {n}
            </Text>
          ))}
        </Card>

        <Text size="xs" tone="tertiary">
          Sharing is set per account, by whoever owns it. Options are:{" "}
          {Object.values(POLICY_LABEL).join(", ")}. Nobody — not even the workspace owner — can
          change how someone else's account is shared.
        </Text>
      </Stack>
    </>
  );
}
