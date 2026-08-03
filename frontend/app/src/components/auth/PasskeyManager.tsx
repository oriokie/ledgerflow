import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { startRegistration, browserSupportsWebAuthn, WebAuthnError } from "@simplewebauthn/browser";
import { Fingerprint, Trash2 } from "lucide-react";
import { useState } from "react";
import { webauthnApi } from "../../api/auth";
import { ApiError } from "../../api/client";
import type { WebAuthnCredential } from "../../api/types";
import { formatDateLong } from "../../lib/money";
import { Badge, Banner, Button, Card, IconButton, Inline, Stack, Text } from "../../ui";

/**
 * Passkey management for the security settings: list registered passkeys, add a
 * new one (runs the WebAuthn registration ceremony), and remove them. Passkeys
 * are phishing-resistant and satisfy MFA on their own, so this sits alongside
 * the authenticator-app section as a stronger alternative.
 */
export function PasskeyManager() {
  const qc = useQueryClient();
  const supported = browserSupportsWebAuthn();

  const { data: credentials, isLoading } = useQuery({
    queryKey: ["webauthn-credentials"],
    queryFn: webauthnApi.listCredentials,
    enabled: supported,
  });

  const [error, setError] = useState<string | null>(null);

  const enroll = useMutation({
    mutationFn: async (deviceName: string) => {
      const optionsJSON = await webauthnApi.registerOptions();
      const credential = await startRegistration({ optionsJSON: optionsJSON as never });
      return webauthnApi.registerVerify({ credential, device_name: deviceName });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webauthn-credentials"] }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => webauthnApi.deleteCredential(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webauthn-credentials"] }),
  });

  const addPasskey = async () => {
    setError(null);
    const suggested = `${navigator.platform || "This device"}`.slice(0, 60);
    const deviceName = window.prompt("Name this passkey (e.g. iPhone, YubiKey)", suggested) ?? "";
    if (deviceName === "" && suggested === "") return;
    try {
      await enroll.mutateAsync(deviceName || suggested);
    } catch (err) {
      if (err instanceof WebAuthnError || (err instanceof DOMException && err.name === "NotAllowedError")) {
        return; // user dismissed the platform prompt
      }
      setError(err instanceof ApiError ? err.detail : "Couldn't register that passkey.");
    }
  };

  if (!supported) {
    return (
      <Card eyebrow="Passkeys" style={{ marginBottom: "var(--lf-space-6)" }}>
        <Text tone="tertiary" size="sm">
          This browser doesn't support passkeys. Try a recent version of Safari, Chrome, or Edge.
        </Text>
      </Card>
    );
  }

  return (
    <Card
      eyebrow="Passkeys"
      action={
        <Button variant="secondary" icon={<Fingerprint size={15} />} onClick={addPasskey} loading={enroll.isPending}>
          Add passkey
        </Button>
      }
      style={{ marginBottom: "var(--lf-space-6)" }}
    >
      <Stack gap={3}>
        <Text tone="tertiary" size="sm">
          Sign in with your fingerprint, face, or a security key — no password, and phishing-resistant by
          design. A passkey counts as two-factor on its own.
        </Text>

        {isLoading && <Text tone="tertiary" size="sm">Loading…</Text>}

        {credentials && credentials.length === 0 && (
          <Text tone="secondary" size="sm">No passkeys yet.</Text>
        )}

        {credentials?.map((cred: WebAuthnCredential) => (
          <Inline key={cred.id} justify="between" gap={3} style={{ width: "100%" }}>
            <div>
              <Text weight="medium">{cred.device_name || "Passkey"}</Text>
              <Text tone="tertiary" size="xs">
                Added {formatDateLong(cred.created_at)}
                {cred.last_used_at ? ` · last used ${formatDateLong(cred.last_used_at)}` : " · never used"}
              </Text>
            </div>
            <Inline gap={2}>
              {cred.backup_state && <Badge tone="neutral">Synced</Badge>}
              <IconButton
                label={`Remove ${cred.device_name || "passkey"}`}
                icon={<Trash2 size={15} />}
                onClick={() => remove.mutate(cred.id)}
                disabled={remove.isPending}
              />
            </Inline>
          </Inline>
        ))}

        {error && <Banner tone="danger">{error}</Banner>}
      </Stack>
    </Card>
  );
}
