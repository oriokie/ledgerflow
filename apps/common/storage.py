"""Object-storage helpers.

Presigned uploads are the only correct pattern for user-uploaded files at
scale: the app server never proxies file bytes. This helper is written
against `django-storages`' `S3Boto3Storage` (the production backend, see
`config/settings/production.py`) and degrades gracefully — returning
`None` — on any other backend (e.g. local `FileSystemStorage` in dev),
so callers must handle the no-presign case explicitly rather than assume
S3 is always configured.
"""

from __future__ import annotations

from django.core.files.storage import default_storage


def generate_presigned_upload_url(*, key: str, content_type: str, expires_in: int = 900) -> str | None:
    """Returns a presigned S3 PUT URL for `key`, or None if the active
    storage backend doesn't support presigning (e.g. local dev storage)."""
    client = getattr(default_storage, "connection", None)
    bucket_name = getattr(default_storage, "bucket_name", None)
    if client is None or bucket_name is None:
        return None
    s3_client = client.meta.client
    return s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket_name, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def generate_presigned_download_url(
    *, key: str, expires_in: int = 900, filename: str | None = None
) -> str | None:
    """Returns a short-lived presigned S3 GET URL for `key`, or None if the
    active storage backend can't presign — callers then stream the bytes
    themselves. `filename` sets an inline Content-Disposition so browsers
    preview receipts rather than force-download them."""
    client = getattr(default_storage, "connection", None)
    bucket_name = getattr(default_storage, "bucket_name", None)
    if client is None or bucket_name is None:
        return None
    params: dict[str, str] = {"Bucket": bucket_name, "Key": key}
    if filename:
        safe = filename.replace('"', "")
        params["ResponseContentDisposition"] = f'inline; filename="{safe}"'
    return client.meta.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)
