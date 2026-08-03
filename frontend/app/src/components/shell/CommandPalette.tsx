import {
  ArrowLeftRight,
  CornerDownLeft,
  FolderTree,
  Receipt,
  Search,
  Wallet,
  Sparkles,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccounts, useBills, useCategories, useTransactions } from "../../hooks/useFinance";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { Money } from "../../ui";
import { filterCommands, groupCommands, parseQuery, recordCommandUse, type Command } from "./commands";
import { useAsk } from "../../hooks/useIntelligence";

/** A row in the palette — either a static command or a matched record. */
interface Entry {
  id: string;
  label: string;
  /** Right-hand context: a category path, an amount, a due date. */
  meta?: React.ReactNode;
  hint?: string;
  to: string;
  icon: LucideIcon;
}

/** Records are only worth querying once the query is specific enough to
 * narrow anything — a single character matches half the ledger. */
const MIN_RECORD_QUERY = 2;
const MAX_PER_GROUP = 5;

function matches(haystack: string, q: string): boolean {
  return haystack.toLowerCase().includes(q);
}

/**
 * ⌘K global search. Rendered as a native <dialog> (class .lf-cmdk .lf-modal),
 * which the design system already styles and which gives focus containment and
 * Esc-to-close for free. AppShell owns the open flag and the keyboard shortcut.
 *
 * Two tiers of result:
 *   • commands — quick actions and navigation, matched locally and instantly.
 *   • records  — the user's own transactions, accounts, categories and bills.
 *     Accounts/categories/bills come from the caches the app already holds, so
 *     they cost nothing; transactions hit the server's `search` filter behind a
 *     debounce so typing stays smooth.
 *
 * Everything is flattened into one keyboard ring, so ↑/↓/Enter behave the same
 * whether the highlighted row is an action or a transaction from March.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const debounced = useDebouncedValue(query, 200);
  const parsed = useMemo(() => parseQuery(debounced), [debounced]);
  const q = parsed.text.trim().toLowerCase();
  // A sigil is itself a specific-enough signal: `@` with one letter means
  // "accounts starting with", and waiting for three characters would make the
  // syntax feel broken. `$` needs no text at all — the amount *is* the query.
  const searchRecords =
    open && (q.length >= MIN_RECORD_QUERY || (!!parsed.sigil && parsed.sigil !== ">"));

  // Cached lists — already in memory for the rest of the app.
  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const { data: bills } = useBills();
  // Server-side search, debounced, and only while the palette is open with a
  // query specific enough to be worth a round-trip.
  const { data: txPage } = useTransactions(
    {
      // `$` asks a question about amounts, so the text is not a search term.
      search: parsed.sigil === "$" ? "" : parsed.text.trim(),
      min_amount_minor: parsed.amount?.min,
      max_amount_minor: parsed.amount?.max,
      page_size: MAX_PER_GROUP,
    },
    searchRecords && (parsed.sigil === null || parsed.sigil === "$"),
  );

  const commandGroups = useMemo(() => groupCommands(filterCommands(query)), [query]);

  /* A question, not a lookup. Only for text that reads like one — otherwise
     every keystroke would be a round trip, and "groceries" is a search term. */
  const looksLikeQuestion = q.length >= 8 && /\s/.test(q) && !parsed.sigil;
  const ask = useAsk(debounced.trim(), open && looksLikeQuestion);

  const recordGroups = useMemo(() => {
    if (!searchRecords) return [] as { group: string; items: Entry[] }[];

    const wants = (kind: "@" | "#" | "$") => parsed.sigil === null || parsed.sigil === kind;

    const accountHits: Entry[] = (!wants("@") ? [] : accounts ?? [])
      .filter((a) => !q || matches(a.name, q))
      .slice(0, MAX_PER_GROUP)
      .map((a) => ({
        id: `account-${a.id}`,
        label: a.name,
        meta: <Money amountMinor={a.balance_minor} currency={a.currency} neutral />,
        to: `/accounts?account=${a.id}`,
        icon: Wallet,
      }));

    const categoryHits: Entry[] = (!wants("#") ? [] : categories ?? [])
      .filter((c) => !q || matches(c.name, q) || matches(c.path, q))
      .slice(0, MAX_PER_GROUP)
      .map((c) => ({
        id: `category-${c.id}`,
        label: c.name,
        meta: c.path,
        to: `/transactions?category_id=${c.id}`,
        icon: FolderTree,
      }));

    const billHits: Entry[] = (parsed.sigil !== null ? [] : bills ?? [])
      .filter((b) => matches(b.name, q))
      .slice(0, MAX_PER_GROUP)
      .map((b) => ({
        id: `bill-${b.id}`,
        label: b.name,
        meta: <Money amountMinor={b.amount_minor} currency={b.currency} neutral />,
        hint: b.due_on,
        to: "/bills",
        icon: Receipt,
      }));

    const txHits: Entry[] = (txPage?.results ?? []).slice(0, MAX_PER_GROUP).map((t) => ({
      id: `tx-${t.id}`,
      label: t.memo || "(no memo)",
      meta: <Money amountMinor={t.amount_minor} currency={t.currency} />,
      hint: t.occurred_at.slice(0, 10),
      to: `/transactions?tx=${t.id}`,
      icon: ArrowLeftRight,
    }));

    return [
      { group: "Transactions", items: txHits },
      { group: "Accounts", items: accountHits },
      { group: "Categories", items: categoryHits },
      { group: "Bills", items: billHits },
    ].filter((g) => g.items.length > 0);
  }, [searchRecords, q, parsed, accounts, categories, bills, txPage]);

  // One flat list backs the keyboard ring, regardless of visual grouping.
  const sections = useMemo(() => {
    const commandSections = commandGroups.map((g) => ({
      group: g.group,
      items: g.items.map(
        (c: Command): Entry => ({
          id: c.id,
          label: c.label,
          hint: c.hint,
          to: c.to,
          icon: c.group === "Actions" ? Zap : CornerDownLeft,
        }),
      ),
    }));
    /* The interpreted question leads, because if it is right it is the answer
       and everything below is noise. It is one row, not a result set: it takes
       you to a *filtered ledger* whose figures the product computed, with the
       filter visible so it can be checked and edited. */
    const askSection = ask.data?.query
      ? [
          {
            group: "Answering your question",
            items: [
              {
                id: "ask-result",
                label: ask.data.explanation || "Show matching transactions",
                hint: describeFilter(ask.data.query),
                to: `/activity?${new URLSearchParams(
                  Object.entries(ask.data.query).map(([k, v]) => [k, String(v)]),
                ).toString()}`,
                icon: Sparkles,
              } as Entry,
            ],
          },
        ]
      : [];

    return [...askSection, ...commandSections, ...recordGroups];
  }, [ask.data, commandGroups, recordGroups]);

  const flat = useMemo(() => sections.flatMap((s) => s.items), [sections]);

  // Keep the native dialog in sync with the controlled `open` flag.
  useEffect(() => {
    const dlg = dialogRef.current;
    if (!dlg) return;
    if (open && !dlg.open) {
      dlg.showModal();
      setQuery("");
      setActive(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    } else if (!open && dlg.open) {
      dlg.close();
    }
  }, [open]);

  // Clamp the highlighted row when the result set shrinks.
  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, flat.length - 1)));
  }, [flat.length]);

  // Keep the highlighted row in view during keyboard traversal.
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const select = (entry: Entry | undefined) => {
    if (!entry) return;
    // Only commands are ranked; a transaction is not a destination you build a
    // habit around, and counting it would bury the destinations you do.
    if (entry.id.startsWith("nav") || entry.id.startsWith("action-")) recordCommandUse(entry.id);
    onClose();
    navigate(entry.to);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (flat.length ? (a + 1) % flat.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (flat.length ? (a - 1 + flat.length) % flat.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      select(flat[active]);
    }
  };

  let cursor = -1;

  return (
    <dialog
      ref={dialogRef}
      className="lf-cmdk lf-modal"
      aria-label="Search LedgerFlow"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
    >
      <div onClick={(e) => e.stopPropagation()}>
        <div className="lf-cmdk-input">
          <Search size={16} strokeWidth={1.8} aria-hidden="true" className="lf-cmdk-input-icon" />
          <input
            ref={inputRef}
            className="lf-input"
            type="text"
            placeholder="Search transactions, accounts, or jump to a page…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Search"
            aria-activedescendant={flat[active] ? `cmdk-${flat[active].id}` : undefined}
            aria-controls="cmdk-results"
            role="combobox"
            aria-expanded
            autoComplete="off"
          />
          <kbd className="lf-kbd">Esc</kbd>
        </div>

        {flat.length === 0 ? (
          <p className="lf-cmdk-empty">
            No matches for “{query}”. Try an account name, a memo, or a page.
          </p>
        ) : (
          <div className="lf-cmdk-list" id="cmdk-results" role="listbox" aria-label="Results" ref={listRef}>
            {sections.map((section) => (
              <div key={section.group} className="lf-cmdk-group">
                <p className="lf-cmdk-group-label">{section.group}</p>
                {section.items.map((entry) => {
                  cursor += 1;
                  const index = cursor;
                  const Icon = entry.icon;
                  return (
                    <button
                      key={entry.id}
                      id={`cmdk-${entry.id}`}
                      type="button"
                      role="option"
                      data-index={index}
                      aria-selected={index === active}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => select(entry)}
                    >
                      <Icon size={15} strokeWidth={1.8} aria-hidden="true" className="lf-cmdk-icon" />
                      <span className="lf-cmdk-label">{entry.label}</span>
                      {entry.meta && <span className="lf-cmdk-meta">{entry.meta}</span>}
                      {entry.hint && <span className="lf-cmdk-hint">{entry.hint}</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        )}

        <div className="lf-cmdk-footer">
          <span>
            <kbd className="lf-kbd">↑</kbd>
            <kbd className="lf-kbd">↓</kbd> to navigate
          </span>
          <span>
            <kbd className="lf-kbd">↵</kbd> to select
          </span>
          <span>
            <kbd className="lf-kbd">?</kbd> for shortcuts
          </span>
        </div>
      </div>
    </dialog>
  );
}

/** The filter, in words, so the user can see what was searched before they
 * trust what comes back. */
function describeFilter(q: Record<string, unknown>): string {
  const bits: string[] = [];
  if (q.direction) bits.push(q.direction === "in" ? "money in" : "money out");
  if (q.category) bits.push(String(q.category));
  if (q.search) bits.push(`"${q.search}"`);
  if (q.start) bits.push(`from ${q.start}`);
  if (q.end) bits.push(`to ${q.end}`);
  if (q.min_amount_minor) bits.push(`over ${Number(q.min_amount_minor) / 100}`);
  if (q.max_amount_minor) bits.push(`under ${Number(q.max_amount_minor) / 100}`);
  return bits.join(" · ") || "all transactions";
}
