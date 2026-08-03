import {
  Banknote,
  CreditCard,
  HandCoins,
  Landmark,
  PiggyBank,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { isLiability } from "./summary";

const ICONS: Record<string, LucideIcon> = {
  checking: Landmark,
  savings: PiggyBank,
  cash: Banknote,
  credit_card: CreditCard,
  loan: HandCoins,
  investment: TrendingUp,
};

/** A rounded, tinted badge with the glyph for an account type. Liability types
 * (credit, loan) get the carmine treatment; assets get iris. */
export function AccountTypeIcon({ type, size = "md" }: { type: string; size?: "md" | "lg" }) {
  const Icon = ICONS[type] ?? Wallet;
  const liability = isLiability(type);
  return (
    <span
      className={`lf-acct-icon${liability ? " lf-acct-icon--liability" : ""}${size === "lg" ? " lf-acct-icon--lg" : ""}`}
      aria-hidden="true"
    >
      <Icon size={size === "lg" ? 22 : 18} strokeWidth={1.8} />
    </span>
  );
}
