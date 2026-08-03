import clsx from "clsx";
import type { ReactNode } from "react";

export type SortDirection = "asc" | "desc";

export interface Column<Row> {
  /** Stable key; also the sort key emitted by onSort. */
  key: string;
  header: ReactNode;
  /** Cell renderer for a row. */
  render: (row: Row) => ReactNode;
  /** Right-align (amounts). */
  align?: "left" | "right";
  /** Hide on narrow screens. */
  hideMobile?: boolean;
  /** Marks the column sortable; header becomes a button. */
  sortable?: boolean;
}

interface TableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  /** Stable key extractor for each row. */
  rowKey: (row: Row) => string;
  /** Row click handler; makes rows interactive. */
  onRowClick?: (row: Row) => void;
  /** Current sort state (for the caret + aria-sort). */
  sort?: { key: string; direction: SortDirection };
  onSort?: (key: string) => void;
  /** Optional accessible caption (visually hidden). */
  caption?: string;
  /** Enable the responsive card-stack layout on mobile. */
  responsive?: boolean;
  /**
   * Pin the header while the body scrolls. Worth it for any ledger long
   * enough to scroll — the column meaning stays on screen.
   */
  stickyHeader?: boolean;
  /**
   * Row selection. Providing `selectedIds` + `onToggleRow` adds a leading
   * checkbox column and a select-all control in the header.
   */
  selectedIds?: ReadonlySet<string>;
  onToggleRow?: (id: string, selected: boolean) => void;
  onToggleAll?: (selected: boolean) => void;
  /** Per-row actions, revealed on hover/focus in a trailing column. */
  rowActions?: (row: Row) => ReactNode;
  /** Rendered in place of the body when there are no rows. */
  empty?: ReactNode;
  className?: string;
}

/**
 * A config-driven table. Columns declare their own alignment, mobile
 * visibility, sortability, and render fn, so pages stop hand-writing
 * `<thead>/<tbody>` and the associated `.lf-col-*` classes. Sorting is
 * controlled: the table renders the caret + aria-sort and calls `onSort(key)`;
 * the parent owns the actual ordering.
 *
 * Selection and row actions are opt-in and additive — a table that passes
 * neither renders exactly the markup it did before.
 */
export function Table<Row>({
  columns,
  rows,
  rowKey,
  onRowClick,
  sort,
  onSort,
  caption,
  responsive = true,
  stickyHeader = false,
  selectedIds,
  onToggleRow,
  onToggleAll,
  rowActions,
  empty,
  className,
}: TableProps<Row>) {
  const selectable = Boolean(selectedIds && onToggleRow);
  const selectedCount = selectedIds?.size ?? 0;
  const allSelected = rows.length > 0 && selectedCount >= rows.length;
  // Indeterminate is the honest state for a partial selection — it tells the
  // user "some, not all" without them having to count.
  const someSelected = selectedCount > 0 && !allSelected;
  const totalColumns = columns.length + (selectable ? 1 : 0) + (rowActions ? 1 : 0);

  if (rows.length === 0 && empty) {
    return <div className="lf-table-wrap">{empty}</div>;
  }

  return (
    <div
      className={clsx("lf-table-wrap", stickyHeader && "lf-table-wrap--sticky")}
      /* A capped, overflowing container is only scrollable with a pointer
         unless it can take focus. WCAG 2.1.1 (keyboard) requires the content
         be reachable, so a sticky-header table gets tabindex=0 and an
         accessible name. Non-sticky tables don't scroll, so giving them a tab
         stop would just add a focus target that does nothing. */
      {...(stickyHeader
        ? { tabIndex: 0, role: "region", "aria-label": caption ?? "Scrollable table" }
        : {})}
    >
      <table className={clsx("lf-table", responsive && "lf-table--responsive", className)}>
        {caption && <caption className="lf-visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {selectable && (
              <th scope="col" className="lf-col-select">
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected;
                  }}
                  onChange={(e) => onToggleAll?.(e.target.checked)}
                  aria-label={allSelected ? "Deselect all rows" : "Select all rows"}
                />
              </th>
            )}
            {columns.map((col) => {
              const isSorted = sort?.key === col.key;
              const ariaSort = isSorted
                ? sort!.direction === "asc"
                  ? "ascending"
                  : "descending"
                : undefined;
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={clsx(
                    col.align === "right" && "lf-col-amount",
                    col.hideMobile && "lf-col-hide-mobile",
                    col.sortable && "lf-th-sortable",
                  )}
                  aria-sort={ariaSort}
                  onClick={col.sortable && onSort ? () => onSort(col.key) : undefined}
                >
                  {col.header}
                  {col.sortable && (
                    <span className="lf-sort-caret" aria-hidden="true">
                      {isSorted ? (sort!.direction === "asc" ? "▲" : "▼") : "↕"}
                    </span>
                  )}
                </th>
              );
            })}
            {rowActions && (
              <th scope="col" className="lf-col-actions">
                <span className="lf-visually-hidden">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={totalColumns} className="lf-table-empty-cell">
                Nothing to show yet.
              </td>
            </tr>
          )}
          {rows.map((row) => {
            const id = rowKey(row);
            const isSelected = selectedIds?.has(id) ?? false;
            return (
              <tr
                key={id}
                data-selected={isSelected || undefined}
                aria-selected={selectable ? isSelected : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                style={onRowClick ? { cursor: "pointer" } : undefined}
              >
                {selectable && (
                  <td className="lf-col-select">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => onToggleRow?.(id, e.target.checked)}
                      // A row can be clickable and selectable at once; the
                      // checkbox must not trigger the row's own handler.
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Select row ${id}`}
                    />
                  </td>
                )}
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={clsx(col.align === "right" && "lf-col-amount", col.hideMobile && "lf-col-hide-mobile")}
                  >
                    {col.render(row)}
                  </td>
                ))}
                {rowActions && (
                  <td className="lf-col-actions">
                    <span
                      className="lf-table-row-actions"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {rowActions(row)}
                    </span>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
