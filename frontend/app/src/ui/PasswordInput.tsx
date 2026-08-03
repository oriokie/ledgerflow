import { Eye, EyeOff } from "lucide-react";
import { useId, useState } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";
import { FormField } from "./Field";

interface PasswordInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  error?: string | null;
  hint?: ReactNode;
}

/**
 * A password field with an accessible reveal toggle. Composes FormField like
 * Input does, so label/error/hint behave identically — but adds a show/hide
 * button that flips the input between password and text. The toggle is a real
 * button with an aria-label that reflects its action, and it doesn't take focus
 * away from the field on click.
 */
export function PasswordInput({ label, error, hint, required, id, className, ...rest }: PasswordInputProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const [visible, setVisible] = useState(false);

  return (
    <FormField label={label} error={error} hint={hint} required={required} htmlFor={fieldId}>
      <div className="lf-password-wrap">
        <input
          id={fieldId}
          type={visible ? "text" : "password"}
          className={["lf-input", className].filter(Boolean).join(" ")}
          aria-invalid={error ? true : undefined}
          required={required}
          {...rest}
        />
        <button
          type="button"
          className="lf-password-toggle"
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          // Prevent the button from stealing focus / triggering blur validation
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setVisible((v) => !v)}
        >
          {visible ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
        </button>
      </div>
    </FormField>
  );
}
