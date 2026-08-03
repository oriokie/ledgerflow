import type { BulkResult } from "../../hooks/useFinance";

/**
 * Turn a bulk-action result into a user-facing message and tone. Full success
 * is celebrated plainly; partial failure reports how many slipped through so the
 * user knows to retry the rest.
 */
export function bulkMessage(
  result: BulkResult,
  verb: string,
): { tone: "success" | "warning" | "danger"; text: string } {
  const done = result.total - result.failed;
  const noun = result.total === 1 ? "transaction" : "transactions";
  if (result.failed === 0) return { tone: "success", text: `${verb} ${result.total} ${noun}.` };
  if (done === 0) return { tone: "danger", text: `None of the ${result.total} ${noun} could be ${verb.toLowerCase()}.` };
  return { tone: "warning", text: `${verb} ${done} of ${result.total} ${noun} — ${result.failed} failed.` };
}
