"""Unit tests for the timesheet reader's pure logic (no OCR model needed)."""

import numpy as np
import pytest

from app.services.extraction.timesheet_grid import (
    WEEKDAYS,
    ParsedSheet,
    SheetCell,
    SheetLine,
    _classify_fill,
    _clean_name,
    _covers,
    _glyphs,
    _parse_labels,
    _SheetReader,
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
    [((220, 38, 38), "REJECTED"), ((245, 158, 11), "SUBMITTED"), ((22, 163, 74), "APPROVED"),
     ((226, 232, 240), "DRAFT"), ((91, 120, 199), "FILLED"), ((255, 255, 255), "EMPTY")],
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
    chars = [(c, float(i)) for i, c in enumerate("Employee IDClientRole")]
    keys = [k for k, _, _ in _parse_labels(chars)]
    assert keys == ["person_id", "supplier", "job_family"]


def test_header_labels_prefer_longest_match():
    chars = [(c, float(i)) for i, c in enumerate("Task Code")]
    assert [k for k, _, _ in _parse_labels(chars)] == ["sub_project_id"]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [("Example ,Juliet", "Example, Juliet"), ("  Demo   User. ", "Demo User")],
)
def test_clean_name(raw, clean):
    assert _clean_name(raw) == clean


def _reader(lines, totals=None, printed=None, period=(2026, 7), days=31):
    """A reader over hand-made lines: the first days are given, the rest of July 2026 is empty."""
    for ln in lines:
        ln.cells += [SheetCell(day=d, hours=None, status="EMPTY", confidence=0.99)
                     for d in range(len(ln.cells) + 1, days + 1)]
    totals = {k: v + [0] * (days - len(v)) for k, v in (totals or {}).items()}
    printed = dict(printed or {})
    if totals and "TOTAL" not in totals:   # real sheets end with a grand total row; mirror the per-type rows
        totals["TOTAL"] = [sum(v[d] or 0 for v in totals.values()) for d in range(days)]
        known = [v for v in printed.values() if v is not None]
        printed["TOTAL"] = sum(known) if known else None
    r = _SheetReader.__new__(_SheetReader)
    r.sheet = ParsedSheet(days_in_month=days, totals=totals, totals_printed_total=printed)
    r.sheet.year, r.sheet.month = period
    r.sheet.person_id = "100001"
    r.lines = lines
    r.day_offset = 0
    return r


def _line(i, uom, hours, total, status="SUBMITTED", conf=0.99):
    cells = [SheetCell(day=d + 1, hours=h, status=status if h is not None else "EMPTY", confidence=conf)
             for d, h in enumerate(hours)]
    return SheetLine(row_index=i, uom=uom, cells=cells, printed_total=total, sub_project=f"p{i}")


def test_reconcile_fills_unreadable_cell_from_row_total():
    ln = _line(0, "REG", [8, 8, None, 0, 0], 24)
    ln.cells[2].status = "SUBMITTED"      # inked but unreadable
    ln.cells[2].confidence = 0.0
    r = _reader([ln], totals={"REG": [8, 8, 8, 0, 0]}, printed={"REG": 24})
    r._reconcile()
    assert ln.cells[2].hours == 8 and ln.cells[2].corrected
    assert r.sheet.status == "CORRECTED"


def test_reconcile_repairs_misread_using_day_and_row_totals():
    ln = _line(0, "REG", [8, 3, 8, None, None], 24)  # '8' misread as '3'
    r = _reader([ln], totals={"REG": [8, 8, 8, 0, 0]}, printed={"REG": 24})
    r._reconcile()
    assert ln.cells[1].hours == 8
    assert r.sheet.verified


def test_reconcile_never_guesses_when_ambiguous():
    a = _line(0, "REG", [4, None, None, None, None], 4)
    b = _line(1, "REG", [3, None, None, None, None], 4)   # one of them is wrong, can't tell which
    r = _reader([a, b], totals={"REG": [8, 0, 0, 0, 0]}, printed={"REG": 8})
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"
    assert a.cells[0].hours == 4 and b.cells[0].hours == 3


def test_out_of_office_detection_is_text_tolerant():
    assert SheetLine(row_index=0, sub_project="Out Of Office").is_out_of_office
    assert SheetLine(row_index=0, sub_project="out of office").is_out_of_office
    assert not SheetLine(row_index=0, sub_project="Safety").is_out_of_office


def test_sheet_without_totals_rows_is_never_verified():
    ln = _line(0, "REG", [8, 8, 8, None, None], 24)
    r = _reader([ln])
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


def test_sheet_without_a_period_is_never_verified():
    ln = _line(0, "REG", [8, 8, 8, None, None], 24)
    r = _reader([ln], totals={"REG": [8, 8, 8, 0, 0]}, printed={"REG": 24}, period=(None, None))
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


def test_a_token_on_the_next_line_does_not_hide_a_missed_line():
    # measured on CI's x86-64 rendering of a wrapped 'Out Of / Office' cell: the detector found only
    # 'Office'; the 'Out Of' line above it sits 1 px from that token's box
    office_token = (381, 245, 423, 266)
    assert not _covers(office_token, (382, 234, 426, 244))   # 'Out Of' line: still recovered
    assert _covers(office_token, (382, 251, 421, 261))       # 'Office' line: already read


def test_a_misread_totals_label_cannot_verify_vacuously():
    # measured: a skewed capture read the only totals row as 'ALNB'; no line has that hour type, so
    # nothing was compared and the sheet was marked verified
    ln = _line(0, "REG", [8, 8, 8, None, None], 24)
    r = _reader([ln], totals={"ALNB": [None] * 5}, printed={"ALNB": None})
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


def test_every_hour_type_on_the_sheet_needs_its_totals_row():
    reg = _line(0, "REG", [8, 8, None, None, None], 16)
    nb = _line(1, "NB", [None, None, 8, None, None], 8)
    r = _reader([reg, nb], totals={"REG": [8, 8, 0, 0, 0]}, printed={"REG": 16})
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


def test_a_partial_grid_is_never_verified():
    # measured: a photo-like capture found only 21 of February's 28 day columns and one of five rows
    ln = _line(0, "REG", [8, 8, 8, None, None], 24)
    r = _reader([ln], totals={"REG": [8, 8, 8, 0, 0]}, printed={"REG": 24}, period=(2026, 2), days=21)
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


def _cell_with(text: str, h: int = 15, w: int = 30) -> np.ndarray:
    import cv2

    img = np.full((h, w, 3), 255, np.uint8)
    cv2.putText(img, text, (3, h - 3), cv2.FONT_HERSHEY_SIMPLEX, h / 32, (30, 30, 30), 1, cv2.LINE_AA)
    return img


def test_a_decimal_point_survives_speck_removal():
    # measured: '3.5' reached the recogniser as '35' (confidence 1.0) because the point was erased as noise
    _, mask, _ = _glyphs(_cell_with("3.5"))
    import cv2

    n, *_ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    assert n - 1 == 3                       # '3', '.', '5'


def test_a_stray_speck_away_from_the_baseline_is_still_removed():
    cell = _cell_with("35")
    cell[2:4, 14:16] = 30                   # speck near the top, between the digits
    _, mask, _ = _glyphs(cell)
    import cv2

    n, *_ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    assert n - 1 == 2


def _box_grid(shadow: float | None = None) -> np.ndarray:
    import cv2

    img = np.full((260, 1100, 3), 252, np.uint8)
    for r in range(3):
        for c in range(28):
            x, y = 40 + c * 36, 60 + r * 40
            cv2.rectangle(img, (x, y), (x + 30, y + 22), (150, 160, 175), 1)
    if shadow is not None:   # light falls off from right to left, down to `shadow` of full brightness
        img = (img * np.linspace(shadow, 1.0, img.shape[1])[None, :, None]).astype(np.uint8)
    return img


def test_uneven_lighting_no_longer_hides_the_day_grid():
    from app.services.extraction.timesheet_grid import _box_lattice, _flatten_lighting

    shadowed = _box_grid(shadow=0.55)
    assert _box_lattice(shadowed) is None                   # measured: shadowed sheets were refused
    lattice = _box_lattice(_flatten_lighting(shadowed))
    assert lattice is not None and len(lattice[1]) == 28 and len(lattice[0]) == 3


def test_evenly_lit_screenshots_are_left_untouched():
    from app.services.extraction.timesheet_grid import _flatten_lighting

    clean = _box_grid()
    assert _flatten_lighting(clean) is clean


def test_a_sheet_without_a_readable_employee_id_is_never_verified():
    # measured: a heavily shadowed sheet read every hour right but the employee ID as '' and was verified
    ln = _line(0, "REG", [8, 8, 8, None, None], 24)
    r = _reader([ln], totals={"REG": [8, 8, 8, 0, 0]}, printed={"REG": 24})
    r.sheet.person_id = ""
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


@pytest.mark.parametrize("task", ["Office", "Out Of", "Payments Out Of"])
def test_a_task_that_could_be_leave_or_work_blocks_verification(task):
    # measured: on a skewed sheet the wrapped 'Out Of / Office' cell split into 'Payments Out Of' and
    # 'Office', the leave row was missed, and the sheet was verified
    ln = _line(0, "NB", [8, 8, 8, None, None], 24)
    ln.sub_project = task
    r = _reader([ln], totals={"NB": [8, 8, 8, 0, 0]}, printed={"NB": 24})
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


@pytest.mark.parametrize("task", ["Out Of Office", "Support", "Customer Portal"])
def test_clear_leave_and_work_tasks_still_verify(task):
    ln = _line(0, "NB", [8, 8, 8, None, None], 24)
    ln.sub_project = task
    r = _reader([ln], totals={"NB": [8, 8, 8, 0, 0]}, printed={"NB": 24})
    r._reconcile()
    assert r.sheet.status == "VERIFIED"


def test_a_sheet_whose_grand_total_row_was_not_read_is_never_verified():
    # measured: every hour right, but the grand total row was not found and the sheet was verified on the
    # per-type rows alone; 'verified' promises agreement with the sheet totals too
    ln = _line(0, "REG", [8, 8, 8, None, None], 24)
    r = _reader([ln], totals={"REG": [8, 8, 8, 0, 0]}, printed={"REG": 24})
    del r.sheet.totals["TOTAL"], r.sheet.totals_printed_total["TOTAL"]
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"


def test_an_unused_hour_type_row_must_total_zero():
    # measured: no row was non-billable, but the NB grand total was misread as 5 and the sheet verified
    ln = _line(0, "REG", [8, 8, 8, None, None], 24)
    r = _reader([ln], totals={"REG": [8, 8, 8, 0, 0], "NB": [0, 0, 0, 0, 0]}, printed={"REG": 24, "NB": 5})
    r.sheet.totals_printed_total["TOTAL"] = 24
    r._reconcile()
    assert r.sheet.status == "NEEDS_REVIEW"
