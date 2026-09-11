/**
 * Read a Safaricom M-Pesa confirmation SMS in the browser.
 *
 * The server re-parses on save — this exists so paste can show the receipt,
 * amount and date in the same second, without a round trip. Keep the rules
 * aligned with `apps/finance/mpesa_sms.py`.
 */

export type MpesaSmsKind =
  | "send_money"
  | "receive"
  | "paybill"
  | "buy_goods"
  | "airtime"
  | "agent_withdrawal"
  | "other";

export interface ParsedMpesaSms {
  receipt: string;
  occurredAt: string;
  amountMinor: number;
  counterparty: string;
  kind: MpesaSmsKind;
  chargeMinor: number;
  balanceMinor: number | null;
}

const RECEIPT = /^\s*([A-Z0-9]{8,12})\s*Confirmed\.?/i;
const KSH = /(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)/gi;
const COST = /Transaction cost[,:]?\s*(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)/i;
const BALANCE =
  /(?:New M-PESA balance is|Your new M-PESA balance is)\s*(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)/i;
const WHEN = /\bon\s+(\d{1,2}\/\d{1,2}\/\d{2,4})\s+at\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b/i;
const PHONE = /\b(?:\+?254|0)\d{8,9}\b/g;

interface KindRule {
  pattern: RegExp;
  kind: MpesaSmsKind;
  inflow: boolean;
}

const KIND_RULES: KindRule[] = [
  {
    pattern: /(?:You have\s+)?received\s+(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+from\s+(.+?)\s+on\s+/i,
    kind: "receive",
    inflow: true,
  },
  {
    pattern: /(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+paid to\s+(.+?)(?:\s+on\s+|\.\s+on\s+)/i,
    kind: "buy_goods",
    inflow: false,
  },
  {
    pattern: /(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+sent to\s+(.+?)\s+on\s+/i,
    kind: "send_money",
    inflow: false,
  },
  {
    pattern:
      /Withdraw(?:n)?\s+(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+from\s+(.+?)(?:\s+New |\s+Transaction |\s*$)/i,
    kind: "agent_withdrawal",
    inflow: false,
  },
  {
    pattern: /bought\s+(?:Ksh|KES)\s*([\d,]+(?:\.\d{1,2})?)\s+of airtime/i,
    kind: "airtime",
    inflow: false,
  },
];

export function parseMpesaSms(text: string): ParsedMpesaSms | null {
  const collapsed = text.trim().replace(/\s+/g, " ");
  if (!collapsed) return null;
  const receiptMatch = collapsed.match(RECEIPT);
  if (!receiptMatch) return null;

  const classified = classify(collapsed);
  if (!classified) return null;
  let { kind, inflow, amountRaw, whoRaw } = classified;
  let amountMinor = toMinor(amountRaw);
  if (amountMinor <= 0) return null;
  if (!inflow) amountMinor = -amountMinor;

  const when = parseWhen(collapsed);
  if (!when) return null;

  if (kind === "send_money" && /\s+for account\s+/i.test(whoRaw)) {
    kind = "paybill";
    whoRaw = whoRaw.split(/\s+for account\s+/i)[0] ?? whoRaw;
  }

  const costMatch = COST.exec(collapsed);
  const balanceMatch = BALANCE.exec(collapsed);
  // LastIndex on global clones; COST/BALANCE are not global. Reset anyway.
  COST.lastIndex = 0;
  BALANCE.lastIndex = 0;

  return {
    receipt: receiptMatch[1].toUpperCase(),
    occurredAt: when,
    amountMinor,
    counterparty: cleanParty(whoRaw),
    kind,
    chargeMinor: costMatch ? toMinor(costMatch[1]) : 0,
    balanceMinor: balanceMatch ? toMinor(balanceMatch[1]) : null,
  };
}

function classify(text: string): { kind: MpesaSmsKind; inflow: boolean; amountRaw: string; whoRaw: string } | null {
  for (const rule of KIND_RULES) {
    const match = rule.pattern.exec(text);
    rule.pattern.lastIndex = 0;
    if (!match) continue;
    return { kind: rule.kind, inflow: rule.inflow, amountRaw: match[1], whoRaw: match[2] ?? "" };
  }

  const skip: Array<[number, number]> = [];
  const cost = COST.exec(text);
  COST.lastIndex = 0;
  if (cost && cost.index !== undefined) skip.push([cost.index, cost.index + cost[0].length]);
  const bal = BALANCE.exec(text);
  BALANCE.lastIndex = 0;
  if (bal && bal.index !== undefined) skip.push([bal.index, bal.index + bal[0].length]);

  KSH.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = KSH.exec(text))) {
    if (skip.some(([start, end]) => match!.index >= start && match!.index < end)) continue;
    return { kind: "other", inflow: false, amountRaw: match[1], whoRaw: "" };
  }
  return null;
}

function parseWhen(text: string): string | null {
  const match = WHEN.exec(text);
  WHEN.lastIndex = 0;
  if (!match) return null;
  const dmy = parseDmy(match[1]);
  const hm = parseHm(match[2]);
  if (!dmy || !hm) return null;
  const [year, month, day] = dmy;
  const [hour, minute] = hm;
  const dt = new Date(year, month - 1, day, hour, minute);
  if (dt.getFullYear() !== year || dt.getMonth() !== month - 1 || dt.getDate() !== day) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:00`;
}

function parseDmy(raw: string): [number, number, number] | null {
  const parts = raw.split("/");
  if (parts.length !== 3) return null;
  const a = Number(parts[0]);
  const b = Number(parts[1]);
  const y = Number(parts[2]);
  if (![a, b, y].every((n) => Number.isInteger(n))) return null;
  const year = y >= 100 ? y : 2000 + y;
  if (a > 12) return [year, b, a];
  if (b > 12) return [year, a, b];
  return [year, b, a];
}

function parseHm(raw: string): [number, number] | null {
  const cleaned = raw.trim().toUpperCase().replace(/\./g, "");
  const ampm = cleaned.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/);
  if (ampm) {
    let hour = Number(ampm[1]);
    const minute = Number(ampm[2]);
    const mer = ampm[3];
    if (hour === 12) hour = mer === "AM" ? 0 : 12;
    else if (mer === "PM") hour += 12;
    return [hour, minute];
  }
  const h24 = cleaned.match(/^(\d{1,2}):(\d{2})$/);
  if (!h24) return null;
  return [Number(h24[1]), Number(h24[2])];
}

function cleanParty(raw: string): string {
  return raw.replace(PHONE, "").replace(/\s+/g, " ").replace(/^[.\-\s]+|[.\-\s]+$/g, "").trim();
}

function toMinor(raw: string): number {
  return Math.round(Number(raw.replace(/,/g, "")) * 100);
}

export function formatMpesaWhen(isoLocal: string): string {
  const d = new Date(isoLocal);
  if (Number.isNaN(d.getTime())) return isoLocal;
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(d);
}
