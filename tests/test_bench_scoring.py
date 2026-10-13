"""The OCR benchmark's outcome classes, in particular the safety metric 'verified_wrong'."""

from scripts.bench_ocr import classify

READ_OK = {"numeric_ok": True, "exact": True}
TEXT_SLIP = {"numeric_ok": True, "exact": False}
NUMBERS_WRONG = {"numeric_ok": False, "exact": False}


def test_verified_and_right_is_exact():
    assert classify("VERIFIED", READ_OK, "exact") == "exact"
    assert classify("CORRECTED", READ_OK, "exact") == "exact"


def test_a_wrong_number_on_a_verified_sheet_is_the_dangerous_outcome():
    assert classify("VERIFIED", NUMBERS_WRONG, "exact") == "verified_wrong"


def test_free_text_slips_are_reported_separately():
    assert classify("VERIFIED", TEXT_SLIP, "exact") == "verified_text_slip"


def test_needs_review_and_refusal_are_flagged():
    assert classify("NEEDS_REVIEW", NUMBERS_WRONG, "exact") == "flagged"
    assert classify(None, None, "exact") == "flagged"


def test_a_handwritten_correction_must_be_flagged_even_if_the_print_is_read_right():
    assert classify("VERIFIED", READ_OK, "flagged") == "verified_wrong"
    assert classify("NEEDS_REVIEW", READ_OK, "flagged") == "flagged"
