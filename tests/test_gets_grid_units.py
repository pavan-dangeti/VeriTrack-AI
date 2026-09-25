"""Unit tests for the GETS reader's pure logic (no OCR model needed)."""

import numpy as np
import pytest

from app.services.extraction.gets_grid import (
    WEEKDAYS,
    GetsCell,
    GetsLine,
    GetsSheet,
    _classify_fill,
    _clean_name,
    _GetsReader,
    _glyphs,
    _parse_labels,
    parse_number,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("8", 8), (" 7 ", 7), ("7.5", 7.5), ("7,5", 7.5), ("O", 0), ("。", 0), ("[47", 47),
     ("B", 8), ("l6", 16), ("", None), ("ab", None), ("1234", None), ("8h", None)],
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize(
    ("rgb", "status"),
    [((193, 54, 122), "USER_SIGNED"), ((255, 249, 208), "PM_APPROVED"),
     ((228, 228, 228), "LM_APPROVED"), ((91, 120, 199), "PLANNED"), ((255, 255, 255), "EMPTY")],
)
def test_cell_fill_classification(rgb, status):
    assert _classify_fill(rgb) == status


def test_glyphs_ignore_border_remnants_and_specks():
    cell = np.full((20, 24, 3), 255, np.uint8)
    cell[:, 0] = 120            # a box border hugging the left edge
    cell[3, 20] = 0             # a JPEG speck
    _fill, _mask, bbox = _glyphs(cell)
    assert bbox is None         # nothing that is a digit
    cell[5:15, 10:13] = 0       # a '1'
    _fill, _mask, bbox = _glyphs(cell)
    assert bbox == (10, 5, 12, 14)


def test_header_labels_parse_merged_ocr_text():
    chars = [(c, float(i)) for i, c in enumerate("Person IDSupplierBillable Job Family")]
    keys = [k for k, _, _ in _parse_labels(chars)]
    assert keys == ["person_id", "supplier", "job_family"]


def test_header_labels_prefer_longest_match():
    chars = [(c, float(i)) for i, c in enumerate("Sub Project ID")]
    assert [k for k, _, _ in _parse_labels(chars)] == ["sub_project_id"]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [("EXAMPLE,J(J.)", "EXAMPLE, J (J.)"), ("  DEMO USER ,K (K.) ", "DEMO USER, K (K.)")],
)
def test_clean_name(raw, clean):
    assert _clean_name(raw) == clean


def _reader(lines, totals=None, printed=None, period=(2026, 7)):
    r = _GetsReader.__new__(_GetsReader)
    r.sheet = GetsSheet(days_in_month=5, totals=totals or {}, totals_printed_total=printed or {})
    r.sheet.year, r.sheet.month = period
    r.lines = lines
    r.day_offset = 0
    return r


def _line(i, uom, hours, total, status="USER_SIGNED", conf=0.99):
    cells = [GetsCell(day=d + 1, hours=h, status=status if h is not None else "EMPTY", confidence=conf)
             for d, h in enumerate(hours)]
    return GetsLine(row_index=i, uom=uom, cells=cells, printed_total=total, sub_project=f"p{i}")


def test_reconcile_fills_unreadable_cell_from_row_total():
    ln = _line(0, "STD", [8, 8, None, 0, 0], 24)
    ln.cells[2].status = "USER_SIGNED"      # inked but unreadable
    ln.cells[2].confidence = 0.0
    r = _reader([ln], totals={"STD": [8, 8, 8, 0, 0]}, printed={"STD": 24})
    r._reconcile()
    assert ln.cells[2].hours == 8 and ln.cells[2].corrected
    assert r.sheet.status == "CORRECTED"


def test_reconcile_repairs_misread_using_day_and_row_totals():
    ln = _line(0, "STD", [8, 3, 8, None, None], 24)  # '8' misread as '3'
    r = _reader([ln], totals={"STD": [8, 8, 8, 0, 0]}, printed={"STD": 24})
    r._reconcile()
    assert ln.cells[1].hours == 8
    assert r.sheet.verified


def test_reconcile_never_guesses_when_ambiguous():
    a = _line(0, "STD", [4, None, None, None, None], 4)
    b = _line(1, "STD", [3, None, None, None, None], 4)   # one of them is wrong, can't tell which
    r = _reader([a, b], totals={"STD": [8, 0, 0, 0, 0]}, printed={"STD": 8})
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"
    assert a.cells[0].hours == 4 and b.cells[0].hours == 3


def test_out_of_office_detection_is_text_tolerant():
    assert GetsLine(row_index=0, sub_project="Out Of Office").is_out_of_office
    assert GetsLine(row_index=0, sub_project="out of office").is_out_of_office
    assert not GetsLine(row_index=0, sub_project="Safety").is_out_of_office


def test_sheet_without_totals_rows_is_never_verified():
    ln = _line(0, "STD", [8, 8, 8, None, None], 24)
    r = _reader([ln])
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


def test_sheet_without_a_period_is_never_verified():
    ln = _line(0, "STD", [8, 8, 8, None, None], 24)
    r = _reader([ln], totals={"STD": [8, 8, 8, 0, 0]}, printed={"STD": 24}, period=(None, None))
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


def test_ambiguous_weekday_header_does_not_guess_the_month():
    import calendar

    r = _reader([], period=(None, None))
    r.sheet.days_in_month = 31
    # July 2025 and December 2026 both start on a Tuesday and have 31 days
    r.sheet.weekdays = [WEEKDAYS[calendar.weekday(2025, 7, d)] for d in range(1, 32)]
    r._infer_period_from_weekdays()
    assert r.sheet.month is None and r.sheet.year is None
    assert any("several months" in w for w in r.sheet.warnings)
