"""Generic (non-GETS) scan reader: semantic line parsing."""

from app.services.extraction.generic_table import _classify_email, _header_columns, _parse_line


def _words(*texts):
    out, x = [], 0.0
    for t in texts:
        out.append({"text": t, "x0": x, "x1": x + 10 * len(t), "score": 0.99})
        x += 10 * len(t) + 25
    return out


def test_public_mail_domains_are_personal():
    assert _classify_email("bob.t@gmail.com") == "personal_email"
    assert _classify_email("ann@corp.io") == "official_email"


def test_header_columns_match_multiword_aliases():
    cols = _header_columns(_words("Employee", "ID", "Full", "Name", "Company", "Email"))
    assert [c[0] for c in cols] == ["employee_code", "full_name", "official_email"]


def test_semantic_parse_when_columns_do_not_line_up():
    values = _parse_line(_words("S-202", "Bob", "Tan", "bob.t", "@", "gmail.com"), [])
    assert values["employee_code"] == "S-202"
    assert values["full_name"] == "Bob Tan"
    assert values["personal_email"] == "bob.t@gmail.com"


def test_glued_id_and_name_are_split():
    values = _parse_line(_words("S-404Dev", "Patel", "dev.p@corp.io"), [])
    assert values["employee_code"] == "S-404"
    assert values["full_name"] == "Dev Patel"
    assert values["official_email"] == "dev.p@corp.io"
