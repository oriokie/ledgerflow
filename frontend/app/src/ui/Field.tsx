import clsx from "clsx";
import { AlertCircle, Check } from "lucide-react";
import { useId } from "react";
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { Spinner } from "./Feedback";

interface FieldShellProps {
  label?: ReactNode;
  /** Error message; presence flips the field into the invalid state. */
  error?: string | null;
  /** Confirmation message; presence flips the field into the valid state. */
  success?: string | null;
  /** Muted helper text under the control. Stays visible alongside success,
   * and is replaced by the error when one is present. */
  hint?: ReactNode;
  required?: boolean;
  /** Marks an optional field explicitly. Preferred over starring the
   * required ones when most of a form is mandatory. */
  optional?: boolean;
  /** Awaiting an async check (availability, FX lookup). */
  busy?: boolean;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}

/**
 * The label + control + message envelope. Every form control below composes
 * this, so the `.lf-field` / `.lf-label` / `.lf-error` markup lives in exactly
 * one place instead of being copy-pasted 90+ times.
 *
 * Message precedence is error → success → hint: a field never shows a
 * contradiction, and the slot keeps a stable height so validation doesn't
 * shift the form under the user's cursor.
 */
export function FormField({
  label,
  error,
  success,
  hint,
  required,
  optional,
  busy,
  htmlFor,
  children,
  className,
}: FieldShellProps) {
  return (
    <div
      className={clsx(
        "lf-field",
        error && "lf-field--invalid",
        !error && success && "lf-field--valid",
        busy && "lf-field--busy",
        className,
      )}
    >
      {label && (
        <label className="lf-label" htmlFor={htmlFor}>
          {label}
          {required && (
            <span aria-hidden="true" style={{ color: "var(--lf-status-danger)" }}>
              *
            </span>
          )}
          {optional && !required && <span className="lf-label-optional">Optional</span>}
          {busy && <Spinner size="sm" label="Checking" />}
        </label>
      )}
      {children}
      {error ? (
        <p className="lf-error" role="alert">
          <AlertCircle size={13} strokeWidth={2} aria-hidden="true" style={{ flexShrink: 0, marginTop: 2 }} />
          {error}
        </p>
      ) : success ? (
        <p className="lf-success-text" role="status">
          <Check size={13} strokeWidth={2.4} aria-hidden="true" style={{ flexShrink: 0, marginTop: 2 }} />
          {success}
        </p>
      ) : hint ? (
        <p className="lf-hint">{hint}</p>
      ) : null}
    </div>
  );
}

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: ReactNode;
  error?: string | null;
  success?: string | null;
  hint?: ReactNode;
  optional?: boolean;
  busy?: boolean;
  /** Ledger/monospace amount styling for currency inputs. */
  amount?: boolean;
  /** Static leading adornment — a currency symbol, an @, a search icon. */
  leading?: ReactNode;
  /** Static trailing adornment — a unit, a currency code. */
  trailing?: ReactNode;
}

/** Text input wired to a FormField. `error` drives the invalid styling and the
 * message; `amount` switches to the monospace ledger treatment; `leading` and
 * `trailing` render non-interactive adornments inside the control. */
export function Input({
  label,
  error,
  success,
  hint,
  optional,
  busy,
  amount,
  leading,
  trailing,
  required,
  id,
  className,
  ...rest
}: InputProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;

  const control = (
    <input
      id={fieldId}
      className={clsx(
        "lf-input",
        amount && "lf-input--amount",
        leading && "lf-input--has-lead",
        trailing && "lf-input--has-trail",
        className,
      )}
      aria-invalid={error ? true : undefined}
      required={required}
      {...rest}
    />
  );

  return (
    <FormField
      label={label}
      error={error}
      success={success}
      hint={hint}
      required={required}
      optional={optional}
      busy={busy}
      htmlFor={fieldId}
    >
      {leading || trailing ? (
        <span className="lf-input-wrap">
          {leading && (
            <span className="lf-input-affix lf-input-affix--lead" aria-hidden="true">
              {leading}
            </span>
          )}
          {control}
          {trailing && (
            <span className="lf-input-affix lf-input-affix--trail" aria-hidden="true">
              {trailing}
            </span>
          )}
        </span>
      ) : (
        control
      )}
    </FormField>
  );
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  error?: string | null;
  success?: string | null;
  hint?: ReactNode;
  optional?: boolean;
}

export function Textarea({
  label,
  error,
  success,
  hint,
  optional,
  required,
  id,
  className,
  rows = 3,
  ...rest
}: TextareaProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FormField
      label={label}
      error={error}
      success={success}
      hint={hint}
      required={required}
      optional={optional}
      htmlFor={fieldId}
    >
      <textarea
        id={fieldId}
        rows={rows}
        className={clsx("lf-input", className)}
        aria-invalid={error ? true : undefined}
        required={required}
        {...rest}
      />
    </FormField>
  );
}

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  label?: ReactNode;
  error?: string | null;
  success?: string | null;
  hint?: ReactNode;
  optional?: boolean;
  /** Options can be passed as data or as raw <option> children. */
  options?: SelectOption[];
  placeholder?: string;
  children?: ReactNode;
}

export function Select({
  label,
  error,
  success,
  hint,
  optional,
  options,
  placeholder,
  required,
  id,
  className,
  children,
  ...rest
}: SelectProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FormField
      label={label}
      error={error}
      success={success}
      hint={hint}
      required={required}
      optional={optional}
      htmlFor={fieldId}
    >
      <select
        id={fieldId}
        className={clsx("lf-select", className)}
        aria-invalid={error ? true : undefined}
        required={required}
        {...rest}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options
          ? options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))
          : children}
      </select>
    </FormField>
  );
}
