import type { ReceivableKind, ReceivableStatus } from "../../api/receivables";

/**
 * Labels for the receivable enums.
 *
 * Kept out of the components because the same words appear in the list, the
 * form and the summary, and three copies drift — always toward the one nobody
 * reads. Mirrors `incomeCopy` for the same reason.
 */

export const KIND_LABEL: Record<ReceivableKind, string> = {
  personal: "Money I lent someone",
  invoice: "Unpaid invoice",
  reimbursement: "Owed a reimbursement",
  deposit: "Deposit held by someone else",
  other: "Something else",
};

export const STATUS_LABEL: Record<ReceivableStatus, string> = {
  outstanding: "Outstanding",
  settled: "Settled",
  written_off: "Written off",
};

/**
 * How a claim's age reads in the list.
 *
 * A due date, where one exists, is the stronger signal — it is something both
 * parties agreed to. Where none exists (the common case for informal lending)
 * the honest fallback is simply how long the money has been out, which is what
 * turns "I lent Sam something once" into "that was fourteen months ago".
 */
export function ageNote(row: {
  days_overdue: number | null;
  days_outstanding: number;
  status: ReceivableStatus;
}): { text: string; tone: "neutral" | "warning" | "critical" } {
  if (row.status === "settled") return { text: "Paid back in full", tone: "neutral" };
  if (row.status === "written_off") return { text: "Written off", tone: "neutral" };

  if (row.days_overdue !== null) {
    if (row.days_overdue > 30) {
      return { text: `${row.days_overdue} days overdue`, tone: "critical" };
    }
    if (row.days_overdue > 0) {
      return { text: `${row.days_overdue} days overdue`, tone: "warning" };
    }
    return { text: `Due in ${Math.abs(row.days_overdue)} days`, tone: "neutral" };
  }

  const months = Math.floor(row.days_outstanding / 30);
  if (months >= 12) {
    return { text: `Outstanding for over a year`, tone: "critical" };
  }
  if (months >= 3) {
    return { text: `Outstanding ${months} months`, tone: "warning" };
  }
  return { text: `Lent ${row.days_outstanding} days ago`, tone: "neutral" };
}
