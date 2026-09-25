"""Magic-byte content inspection tests — disguised files must be rejected."""

import io
import zipfile

import pytest

from app.services.file_validation import FileValidationError, sniff_content_type


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    buf = io.BytesIO()
    wb = Workbook()
    wb.active.append(["Employee ID", "Name"])
    wb.save(buf)
    return buf.getvalue()


def _pdf_bytes() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "hello")
    c.showPage()
    c.save()
    return buf.getvalue()


class TestSniffing:
    def test_pdf_ok(self):
        assert sniff_content_type(_pdf_bytes(), "sheet.pdf") == "application/pdf"

    def test_png_renamed_to_pdf_rejected(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        with pytest.raises(FileValidationError) as e:
            sniff_content_type(png, "evil.pdf")
        assert e.value.code == "extension_mismatch"

    def test_exe_disguised_as_csv_rejected(self):
        binary = bytes(range(256)) * 32
        with pytest.raises(FileValidationError):
            sniff_content_type(binary, "data.csv")

    def test_plain_text_with_xlsx_name_rejected(self):
        with pytest.raises(FileValidationError) as e:
            sniff_content_type(b"id,name\n1,John\n", "table.xlsx")
        assert e.value.code == "type_mismatch"

    def test_zip_disguised_as_xlsx_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("malware.sh", "rm -rf /")
        with pytest.raises(FileValidationError) as e:
            sniff_content_type(buf.getvalue(), "book.xlsx")
        assert e.value.code == "zip_disguised"

    def test_genuine_xlsx_ok(self):
        data = _xlsx_bytes()
        ct = sniff_content_type(data, "book.xlsx")
        assert ct.endswith("sheet")

    def test_jpeg_magic(self):
        jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        assert sniff_content_type(jpg, "scan.jpg") == "image/jpeg"

    def test_ole2_xls_magic(self):
        xls = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
        assert sniff_content_type(xls, "old.xls") == "application/vnd.ms-excel"

    def test_csv_ok(self):
        assert sniff_content_type(b"a,b,c\n1,2,3\n", "rows.csv") == "text/csv"
