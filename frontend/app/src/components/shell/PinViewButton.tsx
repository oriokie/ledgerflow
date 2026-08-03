import { Pin, PinOff } from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { isPinned, suggestLabel, usePinnedViews } from "../../lib/pinnedViews";
import { Button, Input, Modal, Text } from "../../ui";

/**
 * Pins the view you are looking at.
 *
 * Lives in the topbar rather than on each page, because a pin is a property of
 * the *location*, and the shell is the only thing that always knows the
 * location. That also means no page has to opt in: a filter you built in
 * Activity, a report with a range selected, a Plan tab — all pinnable the day
 * they exist.
 *
 * Naming is a step rather than a silent default because the point of a pin is
 * recognising it later. "Activity · filtered" is a bad rail item; "Groceries
 * this month" is the one worth having. The suggestion is pre-filled so the
 * common case is still type-nothing-and-Enter.
 */
export function PinViewButton() {
  const location = useLocation();
  const { pins, pin, unpin, full, max } = usePinnedViews();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");

  const to = `${location.pathname}${location.search}`;
  const pinned = isPinned(pins, to);

  if (pinned) {
    return (
      <button
        type="button"
        className="lf-btn lf-btn--ghost lf-iconbtn"
        onClick={() => unpin(to)}
        aria-label="Unpin this view"
        title="Unpin this view"
      >
        <PinOff size={17} strokeWidth={1.8} aria-hidden="true" />
      </button>
    );
  }

  return (
    <>
      <button
        type="button"
        className="lf-btn lf-btn--ghost lf-iconbtn"
        onClick={() => {
          setLabel(suggestLabel(to));
          setOpen(true);
        }}
        aria-label="Pin this view"
        title="Pin this view"
      >
        <Pin size={17} strokeWidth={1.8} aria-hidden="true" />
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Pin this view"
        description="It'll sit at the top of the sidebar, one click away."
        size="sm"
        footerStart={
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        }
        footer={
          <Button
            variant="primary"
            disabled={full}
            onClick={() => {
              pin(label, to);
              setOpen(false);
            }}
          >
            Pin
          </Button>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (full) return;
            pin(label, to);
            setOpen(false);
          }}
        >
          <Input
            label="Name"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            autoFocus
            hint={to}
          />
        </form>

        {full && (
          <Text tone="secondary" size="sm">
            You have {max} pins, which is the limit — a rail of pins is a rail
            nobody scans. Remove one to add another.
          </Text>
        )}
      </Modal>
    </>
  );
}
