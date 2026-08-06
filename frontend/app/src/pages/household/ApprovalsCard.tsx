import { useState } from "react";
import { ApiError } from "../../api/client";
import type { SpendApproval } from "../../api/household";
import { approvalApi } from "../../api/household";
import { Clock, MessageSquare, ShieldCheck } from "lucide-react";
import { Banner, Button, Card, EmptyState, Input, Stack, Text } from "../../ui";

const money = (minor: number, currency: string) =>
  `${currency} ${(minor / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/** The wording differs by kind, and that is the whole point.
 *
 *  A REQUESTED approval is a decision — the money has not moved and approving
 *  permits a purchase. A FLAGGED one is a review — the money already moved and
 *  approving means "seen, and I'm content". Presenting the second as the first
 *  would have the interface claim it blocked something it merely noticed. */
export const COPY = {
  requested: {
    lead: (a: SpendApproval) => `${a.requested_by} is asking about a purchase`,
    yes: "Approve",
    no: "Not now",
    note: "They have not spent this yet.",
  },
  flagged: {
    lead: () => "A large transaction went out",
    yes: "Looks fine",
    no: "Let's talk",
    note: "This has already been paid — reviewing it does not undo it.",
  },
} as const;

export function timeLeft(expiresAt: string | null): string | null {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "expired";
  const hours = Math.round(ms / 3_600_000);
  if (hours < 24) return `${hours}h left to answer`;
  return `${Math.round(hours / 24)}d left to answer`;
}

function Approval({ item, onChanged }: { item: SpendApproval; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggested, setSuggested] = useState("");
  const [error, setError] = useState<string | null>(null);
  const copy = COPY[item.kind];

  const act = async (body: Parameters<typeof approvalApi.act>[1]) => {
    setBusy(true);
    setError(null);
    try {
      await approvalApi.act(item.id, body);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "That did not go through.");
    } finally {
      setBusy(false);
    }
  };

  const left = timeLeft(item.expires_at);

  return (
    <div className="lf-approval">
      <div className="lf-approval-head">
        <div>
          <Text weight="medium">{copy.lead(item)}</Text>
          <Text tone="tertiary" size="xs">
            {item.description}
          </Text>
        </div>
        <Text weight="medium" className="lf-num">
          {money(item.amount_minor, item.currency)}
        </Text>
      </div>

      <Text tone="tertiary" size="xs">
        {copy.note}
        {left && (
          <>
            {" · "}
            <Clock size={12} strokeWidth={1.8} aria-hidden="true" /> {left}
          </>
        )}
      </Text>

      {item.suggested_amount_minor != null && (
        <Banner tone="info">
          Suggested instead: {money(item.suggested_amount_minor, item.currency)}
        </Banner>
      )}

      {item.comments.length > 0 && (
        <Stack gap={1}>
          {item.comments.map((c, i) => (
            <Text key={i} tone="tertiary" size="xs">
              <MessageSquare size={12} strokeWidth={1.8} aria-hidden="true" /> {c.author}:{" "}
              {c.body}
            </Text>
          ))}
        </Stack>
      )}

      {suggesting ? (
        <Stack gap={2}>
          <Input
            label="Suggest a different amount"
            type="number"
            inputMode="decimal"
            value={suggested}
            onChange={(e) => setSuggested(e.target.value)}
            hint="The request stays open — this is a reply, not a decision."
          />
          <div className="lf-approval-actions">
            <Button
              size="sm"
              loading={busy}
              disabled={!suggested}
              onClick={() =>
                act({ action: "suggest", amount_minor: Math.round(Number(suggested) * 100) })
              }
            >
              Send suggestion
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSuggesting(false)}>
              Cancel
            </Button>
          </div>
        </Stack>
      ) : (
        <div className="lf-approval-actions">
          <Button size="sm" loading={busy} onClick={() => act({ action: "approve" })}>
            {copy.yes}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            loading={busy}
            onClick={() => act({ action: "decline" })}
          >
            {copy.no}
          </Button>
          {item.kind === "requested" && (
            <Button size="sm" variant="ghost" onClick={() => setSuggesting(true)}>
              Suggest a change
            </Button>
          )}
        </div>
      )}

      {error && <Banner tone="danger">{error}</Banner>}
    </div>
  );
}

export function ApprovalsCard({
  items,
  onChanged,
}: {
  items: SpendApproval[];
  onChanged: () => void;
}) {
  const open = items.filter((i) => i.status === "pending");

  return (
    <Card title="Waiting on us" accent="plan">
      {open.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="Nothing to decide"
          body="Purchases over your agreed threshold appear here for the two of you to settle."
        />
      ) : (
        <Stack gap={4}>
          {open.map((item) => (
            <Approval key={item.id} item={item} onChanged={onChanged} />
          ))}
        </Stack>
      )}
    </Card>
  );
}
