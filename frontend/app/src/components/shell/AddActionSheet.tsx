import { ArrowLeftRight, Camera, Plus, Receipt } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Modal } from "../../ui";

const ACTIONS = [
  { to: "/transactions?add=1", label: "Add transaction", hint: "Record something you spent or received", icon: Plus },
  { to: "/receipts/scan", label: "Scan receipt", hint: "Photograph a receipt and let it fill the form", icon: Camera },
  { to: "/bills?add=1", label: "Add bill", hint: "Something you owe on a date", icon: Receipt },
  { to: "/transactions?add=1&type=transfer", label: "Transfer", hint: "Move money between your own accounts", icon: ArrowLeftRight },
] as const;

/**
 * What the bottom bar's centre `+` opens.
 *
 * The old rail listed "Quick Add" and "Scan Receipt" as navigation entries,
 * which is a category error — a verb is not a place. Collected here, they are
 * what they always were: the four things someone opens this app to *do*.
 *
 * Built on `Modal`, which is a native `<dialog>`, so focus containment,
 * Esc-to-close and inertness of the page behind come from the platform rather
 * than from hand-rolled key handlers.
 */
export function AddActionSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add"
      description="What would you like to record?"
      size="sm"
    >
      <ul className="lf-action-sheet">
        {ACTIONS.map((action) => (
          <li key={action.label}>
            <button
              type="button"
              className="lf-action-item"
              onClick={() => {
                onClose();
                navigate(action.to);
              }}
            >
              <span className="lf-action-icon" aria-hidden="true">
                <action.icon size={18} strokeWidth={2} />
              </span>
              <span className="lf-action-text">
                <span className="lf-action-label">{action.label}</span>
                <span className="lf-action-hint">{action.hint}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
