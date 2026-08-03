import clsx from "clsx";
import { useId } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";

interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  label?: ReactNode;
}

/** iOS-style toggle. Wraps the `.lf-switch` track markup so callers just pass
 * `checked`/`onChange`. Renders an optional inline label. */
export function Switch({ label, id, className, ...rest }: SwitchProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const control = (
    <span className={clsx("lf-switch", className)}>
      <input id={fieldId} type="checkbox" role="switch" {...rest} />
      <span className="lf-switch-track" aria-hidden="true" />
    </span>
  );
  if (!label) return control;
  return (
    // `lf-switch-label` adds the touch target height without changing the
    // switch's own visual size: the 44x26 track is a deliberate, compact
    // visual (see .lf-switch), but the *tappable* region around it should
    // still meet this product's own --lf-touch-target minimum on mobile.
    <label className="lf-inline lf-gap-2 lf-switch-label" htmlFor={fieldId} style={{ cursor: "pointer" }}>
      {control}
      <span className="lf-text-sm">{label}</span>
    </label>
  );
}

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
}

/** Native checkbox with an aligned label. */
export function Checkbox({ label, id, className, ...rest }: CheckboxProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <label className="lf-inline lf-gap-2" htmlFor={fieldId} style={{ cursor: "pointer" }}>
      <input id={fieldId} type="checkbox" className={className} {...rest} />
      {label && <span className="lf-text-sm">{label}</span>}
    </label>
  );
}

interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
}

interface SegmentedProps<T extends string> {
  /** Accessible name for the group (visually hidden legend). */
  legend: string;
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  /** Unique name for the radio group; auto-generated if omitted. */
  name?: string;
  className?: string;
}

/**
 * The pill-style segmented control (expense / income / transfer, monthly /
 * yearly, …). Built on native radios inside a fieldset, so keyboard + screen
 * reader behavior is correct for free. Generic over the value union.
 */
export function SegmentedControl<T extends string>({
  legend,
  value,
  onChange,
  options,
  name,
  className,
}: SegmentedProps<T>) {
  const autoName = useId();
  const groupName = name ?? autoName;
  return (
    <fieldset className={clsx("lf-segmented", className)} style={{ border: 0, padding: 3 }}>
      <legend className="lf-visually-hidden">{legend}</legend>
      {options.map((opt) => {
        const optId = `${groupName}-${opt.value}`;
        return (
          <span key={opt.value} style={{ display: "contents" }}>
            <input
              type="radio"
              id={optId}
              name={groupName}
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
            />
            <label htmlFor={optId}>{opt.label}</label>
          </span>
        );
      })}
    </fieldset>
  );
}
