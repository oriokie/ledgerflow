import { Ban, X } from "lucide-react";
import { useState } from "react";
import type { Category } from "../../api/types";
import { Button } from "../../ui";

/**
 * Floating bar shown while transactions are selected. Categorizing applies the
 * chosen category to every selection; voiding acts on all of them at once.
 */
export function BulkActionBar({
  count,
  categories,
  onCategorize,
  onVoid,
  onClear,
  pending,
}: {
  count: number;
  categories: Category[] | undefined;
  onCategorize: (categoryId: string) => void;
  onVoid: () => void;
  onClear: () => void;
  pending: boolean;
}) {
  const [cat, setCat] = useState("");

  return (
    <div className="lf-bulk-bar" role="region" aria-label="Bulk actions">
      <span className="lf-bulk-count">{count} selected</span>

      <select
        aria-label="Set category for selected"
        value={cat}
        disabled={pending}
        onChange={(e) => {
          const value = e.target.value;
          setCat("");
          if (value) onCategorize(value);
        }}
      >
        <option value="">Categorize…</option>
        {(categories ?? []).map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>

      <Button variant="ghost" size="sm" icon={<Ban size={15} strokeWidth={1.8} />} onClick={onVoid} loading={pending}>
        Void
      </Button>

      <span className="lf-bulk-spacer" />

      <Button variant="ghost" size="sm" icon={<X size={15} strokeWidth={1.8} />} onClick={onClear}>
        Clear
      </Button>
    </div>
  );
}
