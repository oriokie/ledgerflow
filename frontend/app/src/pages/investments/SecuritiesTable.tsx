import type { Security } from "../../api/types";
import { Badge, Table, Text } from "../../ui";

const ASSET_CLASS_LABELS: Record<string, string> = {
  stock: "Stocks",
  etf: "ETFs",
  mutual_fund: "Mutual funds",
  bond: "Bonds",
  crypto: "Crypto",
  cash_equivalent: "Cash investments",
};

/**
 * The securities a workspace tracks.
 *
 * Exists because adding a security produced no visible change anywhere: the
 * page rendered nothing until a *holding* existed, so a user who added one saw
 * the same empty state, added it again, and got "already tracked" — a message
 * that contradicted everything on screen. A tracked instrument is a real thing
 * the workspace owns; it deserves to be shown before it has been traded.
 */
export function SecuritiesTable({ securities }: { securities: Security[] }) {
  const columns = [
    {
      key: "symbol",
      header: "Symbol",
      render: (row: Security) => <strong>{row.symbol}</strong>,
    },
    { key: "name", header: "Name", render: (row: Security) => row.name },
    {
      key: "asset_class",
      header: "Class",
      render: (row: Security) => (
        <Badge tone="neutral">{ASSET_CLASS_LABELS[row.asset_class] ?? row.asset_class}</Badge>
      ),
    },
    {
      key: "sector",
      header: "Sector",
      hideMobile: true,
      render: (row: Security) => row.sector || "—",
    },
    { key: "currency", header: "Currency", render: (row: Security) => row.currency },
    {
      key: "exchange",
      header: "Exchange",
      hideMobile: true,
      render: (row: Security) => row.exchange || "—",
    },
  ];

  if (securities.length === 0) {
    return (
      <Text size="sm" tone="tertiary">
        No securities tracked yet.
      </Text>
    );
  }

  return (
    <Table
      columns={columns}
      rows={securities}
      rowKey={(row) => row.id}
      caption="Securities tracked in this workspace"
      responsive
    />
  );
}
