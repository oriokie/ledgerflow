"""A minimal, real, software FIDO2/WebAuthn authenticator for tests.

This does exactly what a hardware key or platform authenticator does:
generates an ECDSA P-256 keypair, builds a real CBOR attestation object and
authenticatorData, and produces real ASN.1 DER ECDSA signatures over the
authentication assertions. Running the actual server-side verification
(`webauthn.verify_registration_response` / `verify_authentication_response`)
against output from this class is a genuine cryptographic proof that the
service layer is correct — not a mock standing in for one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from webauthn.helpers import bytes_to_base64url

_AAGUID_ZERO = b"\x00" * 16


def _cose_public_key(public_numbers: ec.EllipticCurvePublicNumbers) -> bytes:
    x = public_numbers.x.to_bytes(32, "big")
    y = public_numbers.y.to_bytes(32, "big")
    # COSE_Key map for an EC2 P-256 key: kty=EC2(2), alg=ES256(-7), crv=P-256(1)
    cose_key = {1: 2, 3: -7, -1: 1, -2: x, -3: y}
    return cbor2.dumps(cose_key)


@dataclass
class SoftAuthenticator:
    rp_id: str
    origin: str
    credential_id: bytes = field(default_factory=lambda: hashlib.sha256(b"soft-authenticator").digest()[:16])
    sign_count: int = 0
    _private_key: ec.EllipticCurvePrivateKey = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._private_key = ec.generate_private_key(ec.SECP256R1())

    # -- shared building blocks ------------------------------------------------
    def _rp_id_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def _client_data_json(self, *, type_: str, challenge_b64url: str) -> bytes:
        return json.dumps(
            {"type": type_, "challenge": challenge_b64url, "origin": self.origin, "crossOrigin": False},
            separators=(",", ":"),
        ).encode()

    def _sign(self, data: bytes) -> bytes:
        # WebAuthn assertion signatures are ASN.1 DER-encoded ECDSA over SHA-256 —
        # exactly what `cryptography`'s `sign()` produces for an EC key by default.
        from cryptography.hazmat.primitives import hashes

        return self._private_key.sign(data, ec.ECDSA(hashes.SHA256()))

    # -- registration (navigator.credentials.create) ---------------------------
    def create_credential(self, *, challenge_b64url: str) -> dict:
        flags = 0b01000101  # UP(0) + UV(2) + AT(6)
        auth_data = (
            self._rp_id_hash()
            + bytes([flags])
            + self.sign_count.to_bytes(4, "big")
            + _AAGUID_ZERO
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + _cose_public_key(self._private_key.public_key().public_numbers())
        )
        attestation_object = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data_json(type_="webauthn.create", challenge_b64url=challenge_b64url)

        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation_object),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    # -- authentication (navigator.credentials.get) -----------------------------
    def get_assertion(self, *, challenge_b64url: str, sign_count: int | None = None) -> dict:
        if sign_count is not None:
            self.sign_count = sign_count
        else:
            self.sign_count += 1

        flags = 0b00000101  # UP(0) + UV(2), no AT (no attested credential data on auth)
        auth_data = self._rp_id_hash() + bytes([flags]) + self.sign_count.to_bytes(4, "big")
        client_data = self._client_data_json(type_="webauthn.get", challenge_b64url=challenge_b64url)
        client_data_hash = hashlib.sha256(client_data).digest()

        der_signature = self._sign(auth_data + client_data_hash)
        # Sanity: confirm this is a well-formed DER ECDSA signature (r, s).
        decode_dss_signature(der_signature)

        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(der_signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }
