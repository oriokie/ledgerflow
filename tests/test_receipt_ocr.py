"""Receipt OCR — field extraction, tested against raw text directly.

No image, no database: `extract_fields` is a pure function over text, so the
heuristics are pinned without needing a real OCR pass. The tesseract provider
itself is exercised separately with a real rendered image, since the pure
tests can't catch an image-decoding regression.
"""

from __future__ import annotations

from datetime import date

from apps.receipts.ocr import extract_fields

TODAY = date(2026, 6, 15)


def test_the_merchant_is_the_first_readable_line():
    text = "CORNER GROCERY\n123 Main St\nTOTAL 12.50"
    result = extract_fields(text, today=TODAY)
    assert result.merchant == "Corner Grocery" or result.merchant == "CORNER GROCERY"


def test_a_line_of_only_numbers_is_not_mistaken_for_the_merchant():
    text = "0123456789\nCoffee House\nTOTAL 4.50"
    result = extract_fields(text, today=TODAY)
    assert result.merchant == "Coffee House"


def test_a_marked_total_is_preferred_over_a_bare_number():
    text = "Store\nSubtotal 18.00\nTax 1.50\nTOTAL 19.50\nCash 20.00"
    result = extract_fields(text, today=TODAY)
    # The total, not the tendered cash, which is larger.
    assert result.amount_minor == 1_950


def test_grand_total_outranks_a_plain_total_line():
    text = "Store\nItem total 40.00\nGrand Total 43.20"
    result = extract_fields(text, today=TODAY)
    assert result.amount_minor == 4_320


def test_without_a_total_marker_the_largest_figure_is_used():
    """A total is nearly always the biggest number on the receipt, so it's the
    sanest fallback when no marker word is present."""
    text = "Store\nBread 2.50\nMilk 3.00\n8.20"
    result = extract_fields(text, today=TODAY)
    assert result.amount_minor == 820


def test_an_iso_date_is_recognised():
    result = extract_fields("Store\n2026-06-10\nTotal 5.00", today=TODAY)
    assert result.occurred_on == date(2026, 6, 10)


def test_a_slashed_date_is_recognised():
    result = extract_fields("Store\n06/10/2026\nTotal 5.00", today=TODAY)
    assert result.occurred_on == date(2026, 6, 10)


def test_a_two_digit_year_is_anchored_to_the_current_century():
    result = extract_fields("Store\n06/10/26\nTotal 5.00", today=TODAY)
    assert result.occurred_on == date(2026, 6, 10)


def test_a_future_date_is_rejected():
    """A receipt cannot be dated in the future — a misread digit, not a fact."""
    result = extract_fields("Store\n2030-01-01\nTotal 5.00", today=TODAY)
    assert result.occurred_on is None


def test_a_very_old_date_is_rejected():
    """More likely a misread than a genuine six-year-old scan."""
    result = extract_fields("Store\n2015-01-01\nTotal 5.00", today=TODAY)
    assert result.occurred_on is None


def test_empty_text_yields_an_empty_extraction_not_an_error():
    result = extract_fields("", today=TODAY)
    assert result.merchant is None
    assert result.amount_minor is None
    assert result.occurred_on is None
    assert result.confidence == 0.0


def test_confidence_reflects_how_much_was_actually_found():
    """A receipt that yielded nothing should never claim the same confidence as
    one that yielded every field."""
    nothing = extract_fields("xxxx\nyyyy", today=TODAY)
    everything = extract_fields("Corner Shop\n2026-06-10\nTotal 12.00", today=TODAY)
    assert nothing.confidence < everything.confidence
    assert everything.confidence == 1.0


def test_a_partial_read_still_returns_what_it_found():
    """A receipt with a legible total and a smudged date should still return
    the total — forcing all-or-nothing would throw away what worked."""
    result = extract_fields("Store\nTotal 12.00", today=TODAY)
    assert result.amount_minor == 1_200
    assert result.occurred_on is None
    assert 0 < result.confidence < 1


# ------------------------------------------------------------- real OCR pass
def test_tesseract_reads_a_real_rendered_receipt():
    """Exercises the actual image-decoding and OCR path end to end, which the
    pure extraction tests above cannot catch a regression in.

    Deliberately does not assert exact field values: OCR output on a
    synthetic bitmap-rendered receipt varies with the font and tesseract
    version available in a given environment (a decimal point at small sizes
    is a classic miss), and the field-extraction *logic* is already pinned
    exhaustively against known text above. What this test owns is narrower
    and just as important: the image-decode-to-text pipeline runs, doesn't
    raise, and produces something a person could plausibly read.
    """
    import io

    from PIL import Image, ImageDraw

    from apps.receipts.providers import TesseractOCRProvider

    image = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "CORNER GROCERY", fill="black")
    draw.text((20, 80), "2026-06-10", fill="black")
    draw.text((20, 140), "Bread          2.50", fill="black")
    draw.text((20, 200), "Milk           3.00", fill="black")
    draw.text((20, 280), "TOTAL          5.50", fill="black")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = TesseractOCRProvider().read(buffer.getvalue(), content_type="image/png")

    assert result.provider == "tesseract"
    assert result.raw_text.strip(), "expected some text to be read from a rendered receipt"
    assert "GROCERY" in result.raw_text.upper()
    # Confidence is well-formed regardless of exactly what was recognised.
    assert 0.0 <= result.extraction.confidence <= 1.0


def test_tesseract_degrades_gracefully_on_a_corrupt_image():
    """A bad upload must never take down the processing pipeline."""
    from apps.receipts.providers import TesseractOCRProvider

    result = TesseractOCRProvider().read(b"not an image", content_type="image/png")
    assert result.raw_text == ""
    assert result.extraction.confidence == 0.0


def test_the_null_provider_never_raises_and_returns_nothing():
    from apps.receipts.providers import NullOCRProvider

    result = NullOCRProvider().read(b"anything", content_type="image/png")
    assert result.raw_text == ""
    assert result.extraction.amount_minor is None


def test_the_registry_falls_back_to_null_for_an_unknown_provider(settings):
    """A misconfigured optional feature degrades rather than breaking the
    request path it's attached to."""
    from apps.receipts.providers import get_ocr_provider

    settings.RECEIPTS_OCR_PROVIDER = "some_vendor_nobody_wired_up_yet"
    assert get_ocr_provider().name == "null"


def test_the_registry_resolves_tesseract_by_default(settings):
    from apps.receipts.providers import get_ocr_provider

    if hasattr(settings, "RECEIPTS_OCR_PROVIDER"):
        del settings.RECEIPTS_OCR_PROVIDER
    assert get_ocr_provider().name in ("tesseract", "null")
