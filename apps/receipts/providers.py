"""OCR provider implementations.

Two providers ship, and the choice between them is a settings value, not code:

  * `TesseractOCRProvider` — a real, working local OCR engine. No API key, no
    network call, no per-receipt cost. This is the default specifically so the
    feature works out of the box.
  * `NullOCRProvider` — returns empty text and an empty extraction. Used when
    `tesseract` isn't installed in an environment, or deliberately, to force
    manual entry. Never raises; a missing OCR engine should degrade the
    feature, not break the upload flow.

A cloud vendor (Textract, Google Vision) is a third implementation of the same
protocol, swapped in via `RECEIPTS_OCR_PROVIDER` — nothing else in the app
changes, exactly as swapping the coach's LLM provider doesn't touch
`coach.py`.
"""

from __future__ import annotations

import logging

from .ocr import OCRResult, ReceiptExtraction, extract_fields

logger = logging.getLogger("ledgerflow.receipts")


class NullOCRProvider:
    """No OCR at all. The receipt is stored and viewable; every field is
    filled in by hand. A working fallback beats a broken feature."""

    name = "null"

    def read(self, image_bytes: bytes, *, content_type: str) -> OCRResult:
        return OCRResult(raw_text="", extraction=ReceiptExtraction(confidence=0.0), provider=self.name)


class TesseractOCRProvider:
    """Local OCR via `pytesseract`. No network call, no per-image cost, and no
    photo of anyone's grocery receipt ever leaves the server."""

    name = "tesseract"

    def read(self, image_bytes: bytes, *, content_type: str) -> OCRResult:
        try:
            import io

            import pytesseract
            from PIL import Image, ImageOps
        except ImportError:  # pragma: no cover - environment without the libs
            logger.warning("pytesseract/Pillow not available; returning empty OCR result")
            return OCRResult(raw_text="", extraction=ReceiptExtraction(confidence=0.0), provider=self.name)

        try:
            image = Image.open(io.BytesIO(image_bytes))
            # Receipts are usually greyscale already; forcing it plus a light
            # contrast stretch is the single cheapest accuracy win available
            # without a real preprocessing pipeline.
            image = ImageOps.exif_transpose(image).convert("L")
            image = ImageOps.autocontrast(image)
            raw_text = pytesseract.image_to_string(image)
        except Exception:  # pragma: no cover - corrupt/unreadable image
            logger.exception("OCR read failed")
            return OCRResult(raw_text="", extraction=ReceiptExtraction(confidence=0.0), provider=self.name)

        extraction = extract_fields(raw_text)
        return OCRResult(raw_text=raw_text, extraction=extraction, provider=self.name)


_PROVIDERS = {
    "tesseract": TesseractOCRProvider,
    "null": NullOCRProvider,
}


def get_ocr_provider():
    """Resolve the configured provider.

    Falls back to `null` for an unknown setting rather than raising, matching
    the rest of the product's rule that a misconfigured optional feature
    degrades instead of breaking the request path it's attached to.
    """
    from django.conf import settings

    name = getattr(settings, "RECEIPTS_OCR_PROVIDER", "tesseract")
    provider_cls = _PROVIDERS.get(name, NullOCRProvider)
    return provider_cls()
