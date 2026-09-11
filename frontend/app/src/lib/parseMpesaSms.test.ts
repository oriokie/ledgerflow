import { describe, expect, it } from "vitest";
import { parseMpesaSms } from "./parseMpesaSms";

const SAMPLE_SEND =
  "UI94368KUX Confirmed. Ksh250.00 sent to JOHN  NDUNGU 0707750700 on 9/9/26 at 3:29 PM. New M-PESA balance is Ksh0.00. Transaction cost, Ksh7.00.  Amount you can transact within the day is 498,650.00. See all your balances now https://saf.cx/iqIzU";

describe("parseMpesaSms", () => {
  it("extracts receipt, amount, date, payee and fee from a send confirmation", () => {
    const parsed = parseMpesaSms(SAMPLE_SEND);
    expect(parsed).toEqual(
      expect.objectContaining({
        receipt: "UI94368KUX",
        amountMinor: -25_000,
        chargeMinor: 700,
        counterparty: "JOHN NDUNGU",
        kind: "send_money",
        occurredAt: "2026-09-09T15:29:00",
        balanceMinor: 0,
      }),
    );
  });

  it("reads day-first dates so 13/9 is September, not invalid", () => {
    const parsed = parseMpesaSms(
      "QBR5XYZ12A Confirmed. You have received Ksh1,500.00 from JANE DOE 254712345678 on 13/9/26 at 8:05 AM. New M-PESA balance is Ksh1,500.00.",
    );
    expect(parsed?.kind).toBe("receive");
    expect(parsed?.amountMinor).toBe(150_000);
    expect(parsed?.occurredAt).toBe("2026-09-13T08:05:00");
    expect(parsed?.counterparty).toBe("JANE DOE");
  });

  it("treats 'sent to … for account' as paybill, not a person", () => {
    const parsed = parseMpesaSms(
      "TIA9ABCDE1 Confirmed. Ksh200.00 sent to KPLC PREPAID for account 0141234 on 1/10/26 at 7:15 PM. New M-PESA balance is Ksh50.00. Transaction cost, Ksh3.00.",
    );
    expect(parsed?.kind).toBe("paybill");
    expect(parsed?.counterparty).toBe("KPLC PREPAID");
    expect(parsed?.chargeMinor).toBe(300);
  });

  it("returns null for text that is not a confirmation", () => {
    expect(parseMpesaSms("Hello")).toBeNull();
    expect(parseMpesaSms("")).toBeNull();
  });
});
