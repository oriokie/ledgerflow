import { useMemo } from "react";
import { Text } from "../../ui";

type Level = "" | "weak" | "fair" | "good" | "strong";

/**
 * A lightweight, dependency-free strength gauge. It's guidance, not gatekeeping —
 * the backend runs Django's full validator set (length, common-password,
 * similarity) and remains the source of truth. This just gives live feedback so
 * people aren't surprised at submit. Mirrors the 12-char minimum the API enforces.
 */
function assess(password: string): { score: number; level: Level; hint: string } {
  if (!password) return { score: 0, level: "", hint: "" };

  let score = 0;
  if (password.length >= 12) score += 2;
  else if (password.length >= 8) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;

  if (password.length < 12) {
    return { score: Math.min(score, 1), level: "weak", hint: "Use at least 12 characters." };
  }
  if (score <= 2) return { score: 2, level: "fair", hint: "Add a mix of cases, numbers, or symbols." };
  if (score === 3 || score === 4) return { score: 3, level: "good", hint: "Good — a longer passphrase is even stronger." };
  return { score: 4, level: "strong", hint: "Strong password." };
}

const LABEL: Record<Level, string> = { "": "", weak: "Weak", fair: "Fair", good: "Good", strong: "Strong" };

export function PasswordStrengthMeter({ password }: { password: string }) {
  const { score, level, hint } = useMemo(() => assess(password), [password]);

  if (!password) return null;

  return (
    <div aria-live="polite">
      <div className="lf-strength" role="img" aria-label={`Password strength: ${LABEL[level]}`}>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className="lf-strength-seg" data-on={i < score ? level : undefined} />
        ))}
      </div>
      {hint && (
        <Text tone="tertiary" size="xs" style={{ marginTop: "var(--lf-space-1)" }}>
          {LABEL[level]} · {hint}
        </Text>
      )}
    </div>
  );
}
