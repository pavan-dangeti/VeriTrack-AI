"""company leave register parsing: the date shapes people really type."""

from datetime import date

import pytest

from app.services.extraction.normalize import leave_register_map, normalize_tables
from app.services.extraction.readers import RawTable
from app.services.leave_service import MAX_RANGE_DAYS, expand_row, parse_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-07-17", date(2026, 7, 17)),
        ("17-07-2026", date(2026, 7, 17)),
        ("17/07/2026", date(2026, 7, 17)),
        ("17.07.2026", date(2026, 7, 17)),
        ("07/17/2026", date(2026, 7, 17)),        # unambiguously month-first
        ("17-Jul-2026", date(2026, 7, 17)),
        ("17 July 2026", date(2026, 7, 17)),
        ("Jul 17 2026", date(2026, 7, 17)),
        ("17-07-26", date(2026, 7, 17)),
        ("46220", date(2026, 7, 17)),             # Excel serial
        ("2026-07-17 00:00:00", date(2026, 7, 17)),
        ("2026-07-17T09:30:00Z", date(2026, 7, 17)),
        ("31/02/2026", None),
        ("", None),
        ("tomorrow", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_expand_single_day():
    code, dates, kind = expand_row({"employee_code": "100001", "leave_date": "17-07-2026", "leave_type": "Sick"})
    assert (code, dates, kind) == ("100001", [date(2026, 7, 17)], "Sick")


def test_expand_range_inclusive_and_order_insensitive():
    _, dates, _ = expand_row({"employee_code": "1", "from_date": "23-07-2026", "to_date": "21-07-2026"})
    assert dates == [date(2026, 7, 21), date(2026, 7, 22), date(2026, 7, 23)]


def test_expand_rejects_absurd_ranges():
    _, dates, _ = expand_row({"employee_code": "1", "from_date": "2026-01-01", "to_date": "2026-12-31"})
    assert dates == [] and MAX_RANGE_DAYS < 365


def test_register_header_mapping_variants():
    assert leave_register_map(["Person ID", "Leave Date"]) == {"employee_code": "Person ID", "leave_date": "Leave Date"}
    m = leave_register_map(["Emp Code", "From", "To", "Type"])
    assert m == {"employee_code": "Emp Code", "from_date": "From", "to_date": "To", "leave_type": "Type"}
    assert leave_register_map(["Name", "Date"]) is None
    assert leave_register_map(["Employee ID", "Name"]) is None


def test_leave_rows_only_normalised_for_leave_batches():
    table = RawTable(headers=["Employee ID", "Date"], rows=[["100001", "17-07-2026"]])
    assert normalize_tables([table], kind="COMPANY_LEAVE")[0].values["leave_date"] == "17-07-2026"
    assert normalize_tables([table], kind="GETS") == []            # no name column → not repo data
