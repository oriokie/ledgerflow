import { ArrowLeftRight, Camera, Plus, Target, Wallet } from "lucide-react";
import { Link } from "react-router-dom";

const ACTIONS = [
  { to: "/quick-add", label: "Quick add", icon: Plus },
  { to: "/accounts", label: "Accounts", icon: Wallet },
  { to: "/goals", label: "Goals", icon: Target },
  { to: "/activity", label: "Activity", icon: ArrowLeftRight },
  { to: "/receipts/scan", label: "Scan receipt", icon: Camera },
] as const;

export function QuickActions() {
  return (
    <nav className="lf-cmd-actions" aria-label="Quick actions">
      {ACTIONS.map(({ to, label, icon: Icon }) => (
        <Link key={to} to={to} className="lf-cmd-action">
          <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
          <span>{label}</span>
        </Link>
      ))}
    </nav>
  );
}
