import type { ReactNode } from "react";

export interface TabItem<T extends string> {
  value: T;
  label: ReactNode;
}

interface TabsProps<T extends string> {
  /** Accessible name for the tablist. */
  label: string;
  value: T;
  onChange: (value: T) => void;
  tabs: TabItem<T>[];
}

/**
 * In-page tabs with correct ARIA tablist/tab semantics and keyboard support.
 * Distinct from the mobile bottom nav (`.lf-tabbar`) — this switches content
 * within a page. Content panels are rendered by the parent based on `value`.
 */
export function Tabs<T extends string>({ label, value, onChange, tabs }: TabsProps<T>) {
  const onKeyDown = (e: React.KeyboardEvent) => {
    const idx = tabs.findIndex((t) => t.value === value);
    if (e.key === "ArrowRight") {
      e.preventDefault();
      onChange(tabs[(idx + 1) % tabs.length].value);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      onChange(tabs[(idx - 1 + tabs.length) % tabs.length].value);
    }
  };

  return (
    <div className="lf-tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((tab) => (
        <button
          key={tab.value}
          role="tab"
          type="button"
          className="lf-tab"
          aria-selected={value === tab.value}
          tabIndex={value === tab.value ? 0 : -1}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
