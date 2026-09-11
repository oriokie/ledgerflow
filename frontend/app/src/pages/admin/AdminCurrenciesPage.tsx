import { Inbox } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import type { PlatformCurrency } from "../../api/platform";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { ReasonDialog } from "../../components/admin/AdminShell";
import {
  useCapability,
  useCreatePlatformCurrency,
  usePlatformCurrencies,
  usePlatformMe,
  useRefreshFxRates,
  useSetPlatformCurrencyRate,
  useUpdatePlatformCurrency,
} from "../../hooks/usePlatform";
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Input,
  LoadingBlock,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  useToast,
} from "../../ui";
import type { Column } from "../../ui";
import { day } from "./format";

interface CurrencyDraft {
  code: string;
  name: string;
  symbol: string;
  digits: string;
  usd_rate: string;
  is_active: boolean;
}

const EMPTY_DRAFT: CurrencyDraft = {
  code: "",
  name: "",
  symbol: "",
  digits: "2",
  usd_rate: "",
  is_active: true,
};

function draftFrom(row: PlatformCurrency): CurrencyDraft {
  return {
    code: row.code,
    name: row.name,
    symbol: row.symbol,
    digits: String(row.digits),
    usd_rate: row.usd_rate ?? "",
    is_active: row.is_active,
  };
}

function rateLabel(row: PlatformCurrency): string {
  if (row.code === "USD") return "1 (pivot)";
  if (!row.usd_rate) return "—";
  const n = Number(row.usd_rate);
  if (!Number.isFinite(n)) return row.usd_rate;
  return n.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

/**
 * The ISO catalog every workspace picker reads, plus the USD quote conversion
 * uses. Editing a row here is a commercial/ops decision — not a deploy.
 */
export function AdminCurrenciesPage() {
  const { data: me } = usePlatformMe();
  const can = useCapability(me);
  const { data: rows, isLoading } = usePlatformCurrencies();
  const create = useCreatePlatformCurrency();
  const update = useUpdatePlatformCurrency();
  const setRate = useSetPlatformCurrencyRate();
  const refresh = useRefreshFxRates();
  const toast = useToast();

  const [editing, setEditing] = useState<PlatformCurrency | "new" | null>(null);
  const [draft, setDraft] = useState<CurrencyDraft>(EMPTY_DRAFT);
  const [confirming, setConfirming] = useState<"save" | "refresh" | "force" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const editable = can("fx.manage");
  const creating = editing === "new";

  const openNew = () => {
    setEditing("new");
    setDraft(EMPTY_DRAFT);
    setError(null);
  };

  const openEdit = (row: PlatformCurrency) => {
    setEditing(row);
    setDraft(draftFrom(row));
    setError(null);
  };

  const onConfirmSave = async (reason: string) => {
    setError(null);
    try {
      if (creating) {
        await create.mutateAsync({
          code: draft.code,
          name: draft.name,
          symbol: draft.symbol || draft.code.toUpperCase(),
          digits: Number(draft.digits),
          is_active: draft.is_active,
          usd_rate: draft.usd_rate || undefined,
          reason,
        });
        toast("Currency added to every workspace picker.", { tone: "success" });
      } else if (editing) {
        await update.mutateAsync({
          code: editing.code,
          payload: {
            name: draft.name,
            symbol: draft.symbol,
            digits: Number(draft.digits),
            is_active: draft.is_active,
            reason,
          },
        });
        const nextRate = draft.usd_rate.trim();
        if (editing.code !== "USD" && nextRate && nextRate !== (editing.usd_rate ?? "")) {
          await setRate.mutateAsync({
            code: editing.code,
            payload: { rate: nextRate, source: "manual", reason },
          });
        }
        toast("Catalog updated — the change is in the audit log.", { tone: "success" });
      }
      setConfirming(null);
      setEditing(null);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Could not save the currency.");
    }
  };

  const onConfirmRefresh = async (reason: string) => {
    setError(null);
    try {
      const result = await refresh.mutateAsync({ reason, force: confirming === "force" });
      const extra = result.missing.length
        ? ` Missing from the feed: ${result.missing.join(", ")}.`
        : "";
      toast(
        `Updated ${result.updated} rate${result.updated === 1 ? "" : "s"} from ${result.source}.${extra}`,
        { tone: "success" },
      );
      setConfirming(null);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "The live feed could not be reached.");
    }
  };

  const columns: Column<PlatformCurrency>[] = [
    {
      key: "code",
      header: "Code",
      render: (row) => (
        <div>
          <strong className="lf-admin-code">{row.code}</strong>
          <Text size="xs" tone="tertiary">
            {row.symbol}
          </Text>
        </div>
      ),
    },
    { key: "name", header: "Name", render: (row) => row.name },
    {
      key: "digits",
      header: "Digits",
      hideMobile: true,
      render: (row) => String(row.digits),
    },
    {
      key: "rate",
      header: "USD quote",
      align: "right",
      render: (row) => (
        <Stack gap={1}>
          <span>{rateLabel(row)}</span>
          {row.usd_rate_as_of && (
            <Text size="xs" tone="tertiary">
              {row.usd_rate_source} · {day(row.usd_rate_as_of)}
            </Text>
          )}
        </Stack>
      ),
    },
    {
      key: "state",
      header: "Picker",
      render: (row) =>
        row.is_active ? <Badge tone="success">Offered</Badge> : <Badge tone="neutral">Hidden</Badge>,
    },
    {
      key: "actions",
      header: "",
      render: (row) => (
        <Button
          size="sm"
          variant="ghost"
          disabled={!editable}
          title={editable ? undefined : "Editing currencies needs the fx.manage capability."}
          onClick={() => openEdit(row)}
        >
          Edit
        </Button>
      ),
    },
  ];

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Currencies"
        description="What every workspace can book in, and the USD quotes conversion uses. Adding a code here is what makes it appear in account, bill and goal pickers — without a deploy."
        meta={rows ? `${rows.length} ${rows.length === 1 ? "currency" : "currencies"}` : undefined}
        actions={
          <Stack gap={2} style={{ flexDirection: "row" }}>
            <Button
              variant="secondary"
              disabled={!editable || refresh.isPending}
              onClick={() => {
                setError(null);
                setConfirming("refresh");
              }}
            >
              Fetch live rates
            </Button>
            <Button
              variant="ghost"
              disabled={!editable || refresh.isPending}
              onClick={() => {
                setError(null);
                setConfirming("force");
              }}
            >
              Replace manual rates
            </Button>
            <Button variant="primary" disabled={!editable} onClick={openNew}>
              Add currency
            </Button>
          </Stack>
        }
      />

      {!editable && (
        <Banner tone="info">
          You can see the catalog, but changing it needs the currency-management capability.
        </Banner>
      )}

      {error && confirming && <Banner tone="danger">{error}</Banner>}

      {isLoading && !rows ? (
        <LoadingBlock />
      ) : rows?.length ? (
        <Table columns={columns} rows={rows} rowKey={(r) => r.code} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState
            icon={Inbox}
            title="No currencies"
            body="Seed the catalog so workspaces can pick a books currency."
          />
        </Card>
      )}

      {editing && (
        <Modal
          open
          onClose={() => setEditing(null)}
          title={creating ? "Add a currency" : `Edit ${draft.code}`}
        >
          <Stack gap={3}>
            {creating && (
              <Input
                label="ISO code"
                value={draft.code}
                maxLength={3}
                hint="Three letters. This cannot change later."
                onChange={(e) => setDraft({ ...draft, code: e.target.value.toUpperCase() })}
              />
            )}
            <Input
              label="Name"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
            <div className="lf-grid lf-grid--2 lf-gap-3">
              <Input
                label="Symbol"
                value={draft.symbol}
                onChange={(e) => setDraft({ ...draft, symbol: e.target.value })}
              />
              <Input
                label="Minor-unit digits"
                type="number"
                min="0"
                max="4"
                hint="0 for yen, 2 for most, 3 for dinars."
                value={draft.digits}
                onChange={(e) => setDraft({ ...draft, digits: e.target.value })}
              />
            </div>
            {draft.code !== "USD" && (
              <Input
                label="USD quote"
                type="number"
                min="0"
                step="any"
                hint="How many of this currency one US dollar buys. Leave blank to wait for the live feed."
                value={draft.usd_rate}
                onChange={(e) => setDraft({ ...draft, usd_rate: e.target.value })}
              />
            )}
            <Switch
              label="Offered in pickers"
              checked={draft.is_active}
              onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
            />
            {error && <Banner tone="danger">{error}</Banner>}
            <Button
              variant="primary"
              onClick={() => {
                setError(null);
                setConfirming("save");
              }}
            >
              Save
            </Button>
          </Stack>
        </Modal>
      )}

      <ReasonDialog
        open={confirming === "save"}
        title={creating ? "Add this currency" : "Update the catalog"}
        confirmLabel={creating ? "Add currency" : "Save changes"}
        onConfirm={onConfirmSave}
        onClose={() => setConfirming(null)}
      />
      <ReasonDialog
        open={confirming === "refresh" || confirming === "force"}
        title="Fetch live USD quotes"
        confirmLabel="Refresh rates"
        onConfirm={onConfirmRefresh}
        onClose={() => setConfirming(null)}
      />
    </Stack>
  );
}
