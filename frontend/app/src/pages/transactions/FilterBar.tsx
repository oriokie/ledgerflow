import { Search, SlidersHorizontal, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Category, FinancialAccount } from "../../api/types";
import { Button, Checkbox, Input, Select } from "../../ui";
import {
  activeFilterChips,
  clearFilterField,
  countActiveFilters,
  EMPTY_FILTERS,
  type FilterState,
} from "./filters";

const TYPE_OPTIONS = [
  { value: "", label: "All types" },
  { value: "expense", label: "Expenses" },
  { value: "income", label: "Income" },
  { value: "transfer", label: "Transfers" },
];
const STATUS_OPTIONS = [
  { value: "", label: "Any status" },
  { value: "posted", label: "Posted" },
  { value: "pending", label: "Pending" },
  { value: "void", label: "Void" },
];

export function FilterBar({
  state,
  onChange,
  searchValue,
  onSearchChange,
  accounts,
  categories,
  actions,
}: {
  state: FilterState;
  onChange: (next: FilterState) => void;
  searchValue: string;
  onSearchChange: (value: string) => void;
  accounts?: FinancialAccount[];
  categories?: Category[];
  actions?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const activeCount = countActiveFilters(state);
  const chips = activeFilterChips(state, { accounts, categories });

  const set = (patch: Partial<FilterState>) => onChange({ ...state, ...patch });

  return (
    <>
      <div className="lf-txn-toolbar">
        <div className="lf-search-box">
          <Search size={16} strokeWidth={1.8} aria-hidden="true" />
          <input
            type="search"
            placeholder="Search memo, payee, amount…"
            aria-label="Search transactions"
            value={searchValue}
            onChange={(e) => onSearchChange(e.target.value)}
          />
          {searchValue && (
            <button type="button" className="lf-search-clear" aria-label="Clear search" onClick={() => onSearchChange("")}>
              <X size={14} strokeWidth={2} aria-hidden="true" />
            </button>
          )}
        </div>

        <Button
          variant={open || activeCount ? "secondary" : "ghost"}
          icon={<SlidersHorizontal size={15} strokeWidth={1.8} />}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          Filters
          {activeCount > 0 && <span className="lf-filter-toggle-count">{activeCount}</span>}
        </Button>

        {actions}
      </div>

      {open && (
        <div className="lf-filter-panel">
          <div className="lf-filter-grid">
            <Select
              label="Account"
              value={state.account}
              onChange={(e) => set({ account: e.target.value })}
              options={[{ value: "", label: "All accounts" }, ...(accounts ?? []).map((a) => ({ value: a.id, label: a.name }))]}
            />
            <Select label="Type" value={state.type} onChange={(e) => set({ type: e.target.value as FilterState["type"] })} options={TYPE_OPTIONS} />
            <Select
              label="Category"
              value={state.category}
              onChange={(e) => set({ category: e.target.value })}
              options={[{ value: "", label: "All categories" }, ...(categories ?? []).map((c) => ({ value: c.id, label: c.name }))]}
            />
            <Select label="Status" value={state.status} onChange={(e) => set({ status: e.target.value })} options={STATUS_OPTIONS} />
            <Input label="From" type="date" value={state.start} onChange={(e) => set({ start: e.target.value })} />
            <Input label="To" type="date" value={state.end} onChange={(e) => set({ end: e.target.value })} />
            <Input label="Min amount" type="number" step="0.01" min="0" placeholder="0.00" value={state.min} onChange={(e) => set({ min: e.target.value })} />
            <Input label="Max amount" type="number" step="0.01" min="0" placeholder="0.00" value={state.max} onChange={(e) => set({ max: e.target.value })} />
            <div style={{ display: "flex", alignItems: "flex-end", paddingBottom: 6 }}>
              <Checkbox
                label="Needs review only"
                checked={state.needsReview}
                onChange={(e) => set({ needsReview: e.target.checked })}
              />
            </div>
          </div>
          <div className="lf-filter-actions">
            <Button variant="ghost" onClick={() => onChange({ ...EMPTY_FILTERS, q: state.q })}>
              Reset
            </Button>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Done
            </Button>
          </div>
        </div>
      )}

      {chips.length > 0 && (
        <div className="lf-filter-chips">
          {chips.map((chip) => (
            <span key={chip.key} className="lf-filter-chip">
              {chip.label}
              <button
                type="button"
                aria-label={`Remove filter ${chip.label}`}
                onClick={() => onChange(clearFilterField(state, chip.key))}
              >
                <X size={12} strokeWidth={2} aria-hidden="true" />
              </button>
            </span>
          ))}
          <button type="button" className="lf-filter-clear-all" onClick={() => onChange({ ...EMPTY_FILTERS, q: state.q })}>
            Clear all
          </button>
        </div>
      )}
    </>
  );
}
