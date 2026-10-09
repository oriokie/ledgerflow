import { useEffect, useRef, useState } from "react";
import { authApi, profileApi } from "../../../api/auth";
import { ApiError } from "../../../api/client";
import { useAuth } from "../../../lib/AuthContext";
import { Banner, Button, Input, PasswordInput } from "../../../ui";
import { DangerZone, SaveStatus, SettingsRow, SettingsSection, type SaveState } from "../components";

/** Long enough that a save isn't fired per keystroke, short enough that the
 * confirmation still feels like a response to what you just typed. */
const DEBOUNCE_MS = 800;

export function ProfilePanel() {
  const { user } = useAuth();
  const [firstName, setFirstName] = useState(user?.first_name ?? "");
  const [lastName, setLastName] = useState(user?.last_name ?? "");
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);

  /** What the server is known to hold. Guards the two ways autosave misfires:
   * saving on mount, and saving a value identical to the last one committed. */
  const committed = useRef({ first: user?.first_name ?? "", last: user?.last_name ?? "" });
  /** Responses can land out of order; only the newest may set the status. */
  const seq = useRef(0);

  const save = async (first: string, last: string) => {
    const mine = ++seq.current;
    setState("saving");
    setError(null);
    try {
      await profileApi.update({ first_name: first, last_name: last });
      if (seq.current !== mine) return;
      committed.current = { first, last };
      setState("saved");
    } catch (err) {
      if (seq.current !== mine) return;
      setError(err instanceof ApiError ? err.detail : "Couldn't save your profile.");
      setState("error");
    }
  };

  const dirty = firstName !== committed.current.first || lastName !== committed.current.last;

  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => void save(firstName, lastName), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [firstName, lastName, dirty]);

  /* Leaving a field commits it immediately. Without this, tabbing away and
     navigating within the debounce window silently discards the edit — the
     failure mode that makes people distrust autosave in the first place. */
  const flush = () => {
    if (dirty) void save(firstName, lastName);
  };

  return (
    <SettingsSection title="Profile" description="How your name appears across LedgerFlow.">
      <SettingsRow title="Email" description="The address you sign in with.">
        <span className="lf-settings-readonly">{user?.email}</span>
      </SettingsRow>

      {/* Two controls, so two visible labels. The row heading stays descriptive
          text rather than a `htmlFor` target: pointing one "Name" label at the
          first of two inputs made the visible text the accessible name of
          neither, and left the second field identified only by a placeholder —
          which vanishes the moment anything is typed into it. */}
      <SettingsRow title="Name" description="Shown to workspace members.">
        <div className="lf-settings-field-pair">
          <Input
            id="pf-first"
            label="First name"
            autoComplete="given-name"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            onBlur={flush}
          />
          <Input
            id="pf-last"
            label="Last name"
            autoComplete="family-name"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            onBlur={flush}
          />
        </div>
      </SettingsRow>

      <SaveStatus state={state} error={error} onRetry={() => void save(firstName, lastName)} />

      {!user?.is_verified && (
        <Banner tone="warning">
          Your email is not verified.{" "}
          <Button
            type="button"
            variant="ghost"
            onClick={() => void authApi.requestEmailVerification().then(() => setError(null))}
          >
            Resend confirmation
          </Button>
        </Banner>
      )}

      <DangerZone
        title="Delete account"
        description="Closes workspaces you own and removes your login. This cannot be undone from the app."
      >
        <AccountDeleteForm />
      </DangerZone>
    </SettingsSection>
  );
}

function AccountDeleteForm() {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onDelete = async () => {
    setBusy(true);
    setError(null);
    try {
      await authApi.deleteAccount(password);
      window.location.href = "/logged-out";
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't delete the account.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PasswordInput
        label="Confirm with your password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoComplete="current-password"
      />
      {error && <Banner tone="danger">{error}</Banner>}
      <Button type="button" variant="danger" disabled={!password || busy} loading={busy} onClick={() => void onDelete()}>
        Delete my account
      </Button>
    </>
  );
}
