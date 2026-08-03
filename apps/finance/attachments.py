"""Attachment service layer: receipts/documents via a two-step presigned
upload. The app server never sees file bytes — it issues a scoped, time-
limited presigned PUT URL, the client uploads directly to object storage,
then confirms. This keeps large uploads off the request/response cycle
entirely and is the only pattern that scales past toy file sizes.

Confirmation trusts the client-reported checksum/size in this build (a
transaction not currently retried against real S3 in this environment) —
production hardening is a HEAD request against the object to verify actual
size/ETag before flipping to UPLOADED, noted in FINANCE_ENGINE.md.
"""

from __future__ import annotations

import hashlib
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction

from apps.common.storage import generate_presigned_download_url, generate_presigned_upload_url

from .models import Attachment, AttachmentStatus, Transaction

_MAX_BYTES = 25 * 1024 * 1024  # 25MB — receipts/statements, not video


class AttachmentError(Exception): ...


def _storage_key(*, tenant_id, transaction_id, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"attachments/{tenant_id}/{transaction_id}/{uuid.uuid4()}-{safe_name}"


@transaction.atomic
def request_attachment_upload(
    *, txn: Transaction, filename: str, content_type: str, byte_size: int
) -> tuple[Attachment, str | None]:
    """Creates a PENDING Attachment row and returns (attachment, upload_url).
    `upload_url` is None when the active storage backend doesn't support
    presigning (local dev) — callers should fall back to a direct-write path
    in that environment rather than surface a broken "upload" button."""
    if byte_size <= 0:
        raise AttachmentError("byte_size must be positive.")
    if byte_size > _MAX_BYTES:
        raise AttachmentError(f"Attachment exceeds the {_MAX_BYTES // (1024 * 1024)}MB limit.")

    key = _storage_key(tenant_id=txn.tenant_id, transaction_id=txn.id, filename=filename)
    attachment = Attachment.objects.create(
        transaction=txn,
        storage_key=key,
        content_type=content_type,
        byte_size=byte_size,
        status=AttachmentStatus.PENDING,
    )
    upload_url = generate_presigned_upload_url(
        key=key, content_type=content_type, expires_in=getattr(settings, "ATTACHMENT_UPLOAD_TTL_SECONDS", 900)
    )
    return attachment, upload_url


@transaction.atomic
def confirm_attachment_upload(*, attachment: Attachment, checksum: str = "") -> Attachment:
    if attachment.status == AttachmentStatus.UPLOADED:
        return attachment  # idempotent
    attachment.status = AttachmentStatus.UPLOADED
    attachment.checksum = checksum
    attachment.save(update_fields=["status", "checksum", "updated_at"])
    return attachment


@transaction.atomic
def store_attachment_bytes(*, attachment: Attachment, data: bytes) -> Attachment:
    """Server-side upload path for environments that can't presign (local dev,
    tests, or any non-S3 backend): stream the bytes straight to
    `default_storage` and mark the attachment UPLOADED, recording the real size
    and checksum. In production the client PUTs directly to S3 via the presigned
    URL and never touches this path — so the app server still never proxies file
    bytes at scale; this is the graceful fallback, not the hot path."""
    if not data:
        raise AttachmentError("No file content received.")
    if len(data) > _MAX_BYTES:
        raise AttachmentError(f"Attachment exceeds the {_MAX_BYTES // (1024 * 1024)}MB limit.")

    saved_key = default_storage.save(attachment.storage_key, ContentFile(data))
    attachment.storage_key = saved_key  # storage may de-collide the name
    attachment.byte_size = len(data)
    attachment.checksum = hashlib.sha256(data).hexdigest()
    attachment.status = AttachmentStatus.UPLOADED
    attachment.save(update_fields=["storage_key", "byte_size", "checksum", "status", "updated_at"])
    return attachment


def open_attachment(*, attachment: Attachment):
    """Open the stored blob for streaming. Returns (fileobj, content_type).
    Only used on backends without presigned GETs — S3 callers redirect instead."""
    if attachment.status != AttachmentStatus.UPLOADED:
        raise AttachmentError("Attachment upload has not been confirmed yet.")
    if not default_storage.exists(attachment.storage_key):
        raise AttachmentError("The stored file is no longer available.")
    return default_storage.open(attachment.storage_key, "rb"), attachment.content_type


def presigned_download_url(*, attachment: Attachment) -> str | None:
    """A short-lived presigned GET URL when the backend supports it, else None
    (the caller then streams via `open_attachment`)."""
    if attachment.status != AttachmentStatus.UPLOADED:
        return None
    return generate_presigned_download_url(
        key=attachment.storage_key,
        expires_in=getattr(settings, "ATTACHMENT_DOWNLOAD_TTL_SECONDS", 900),
    )


@transaction.atomic
def delete_attachment(*, attachment: Attachment) -> None:
    attachment.delete()  # soft delete — the object-storage blob is reaped by a lifecycle policy, not here
