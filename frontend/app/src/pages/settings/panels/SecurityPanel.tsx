import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { mfaApi } from "../../../api/auth";
import { ApiError } from "../../../api/client";
import { PasskeyManager } from "../../../components/auth/PasskeyManager";
import { useAuth } from "../../../lib/AuthContext";
import { Badge, Banner, Button, Grid, Inline, Input, Modal, Text } from "../../../ui";
import { SettingsAdvanced, SettingsSection } from "../components";

export function SecurityPanel() {
  const { user } = useAuth();
  const [enrollment, setEnrollment] = useState<{ secret: string; provisioning_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [mfaOn, setMfaOn] = useState(!!user?.mfa_enabled);
  const [error, setError] = useState<string | null>(null);

  const wrap = async (fn: () => Promise<void>, fallback: string) => {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : fallback);
    }
  };

  const startEnroll = () => wrap(async () => setEnrollment(await mfaApi.enrollTotp()), "Couldn't start enrollment.");
  const confirm = () =>
    wrap(async () => {
      const result = await mfaApi.confirmTotp(code);
      setBackupCodes(result.backup_codes);
      setEnrollment(null);
      setCode("");
      setMfaOn(true);
    }, "That code didn't verify.");
  const disable = () =>
    wrap(async () => {
      await mfaApi.disableTotp(code);
      setMfaOn(false);
      setDisabling(false);
      setCode("");
    }, "That code didn't verify.");
  const regenerate = () =>
    wrap(async () => {
      const result = await mfaApi.regenerateBackupCodes(code);
      setBackupCodes(result.backup_codes);
      setRegenerating(false);
      setCode("");
    }, "That code didn't verify.");

  return (
    <>
      <SettingsSection
        title="Two-factor authentication"
        description="Add a 6-digit code from an authenticator app to every sign-in — strongly recommended for an account holding your financial history."
        action={<Badge tone={mfaOn ? "success" : "neutral"}>{mfaOn ? "On" : "Off"}</Badge>}
      >
        {!mfaOn && !enrollment && (
          <div>
            <Button variant="primary" onClick={startEnroll}>
              Set up authenticator
            </Button>
          </div>
        )}

        {enrollment && (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-3)" }}>
            <Text tone="tertiary" size="sm">
              Scan with your authenticator app, then enter the 6-digit code it shows.
            </Text>
            <div className="lf-qr-plate">
              <QRCodeSVG value={enrollment.provisioning_uri} size={168} />
            </div>
            <Text tone="tertiary" size="sm">
              Can't scan? Enter this secret manually: <code className="lf-kbd">{enrollment.secret}</code>
            </Text>
            <Inline gap={2} align="end">
              {/* A visible label, not just an `aria-label`. The placeholder
                  was the only thing on screen naming this field, and a
                  placeholder disappears the moment the first digit is typed —
                  which is exactly when someone glancing away and back needs to
                  know what they were entering. WCAG 3.3.2. */}
              <Input
                label="Verification code"
                style={{ maxWidth: 160 }}
                inputMode="numeric"
                placeholder="123 456"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <Button variant="primary" onClick={confirm}>
                Verify &amp; enable
              </Button>
            </Inline>
          </div>
        )}

        {mfaOn && !enrollment && (
          <SettingsAdvanced label="Advanced two-factor options">
            {!regenerating && !disabling && (
              <Inline gap={2}>
                <Button variant="secondary" onClick={() => setRegenerating(true)}>
                  Regenerate backup codes
                </Button>
                <Button variant="ghost" onClick={() => setDisabling(true)}>
                  Turn off two-factor
                </Button>
              </Inline>
            )}
            {regenerating && (
              <Inline gap={2} align="end">
                <Input
                  label="Current verification code"
                  style={{ maxWidth: 160 }}
                  inputMode="numeric"
                  placeholder="123 456"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
                <Button variant="primary" onClick={regenerate}>
                  Regenerate
                </Button>
                <Button variant="ghost" onClick={() => setRegenerating(false)}>
                  Cancel
                </Button>
              </Inline>
            )}
            {disabling && (
              <Inline gap={2} align="end">
                <Input
                  label="Current verification code"
                  style={{ maxWidth: 160 }}
                  inputMode="numeric"
                  placeholder="123 456"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
                <Button variant="danger" onClick={disable}>
                  Turn off
                </Button>
                <Button variant="ghost" onClick={() => setDisabling(false)}>
                  Cancel
                </Button>
              </Inline>
            )}
          </SettingsAdvanced>
        )}

        {error && <Banner tone="danger">{error}</Banner>}
      </SettingsSection>

      <PasskeyManager />

      <Modal
        open={!!backupCodes}
        onClose={() => setBackupCodes(null)}
        title="Save your backup codes"
        footer={
          <Button variant="primary" onClick={() => setBackupCodes(null)}>
            I've saved them
          </Button>
        }
      >
        <Text tone="tertiary" size="sm">
          Each code works once if you lose your authenticator. Store them somewhere safe — they won't be shown again.
        </Text>
        <Grid cols={2} gap={2} style={{ margin: "var(--lf-space-4) 0" }}>
          {backupCodes?.map((c) => (
            <code key={c} className="lf-kbd" style={{ textAlign: "center" }}>
              {c}
            </code>
          ))}
        </Grid>
      </Modal>
    </>
  );
}
