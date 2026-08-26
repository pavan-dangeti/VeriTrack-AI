"""GETS violation rule edge cases + email resolution priority."""

from app.services import gets_rules
from app.services.extraction.normalize import normalize_row


class TestTickParsing:
    def test_ticked_values(self):
        for v in ["✓", "✔", "☑", "X", "x", "Yes", "YES", "true", "1", "[x]", "√"]:
            assert gets_rules.parse_ticked(v), v

    def test_blank_values(self):
        for v in ["", "   ", "-", "--", "No", "NO", "false", "0", None, "n"]:
            assert gets_rules.parse_blank(v), repr(v)

    def test_tick_is_not_blank(self):
        assert not gets_rules.parse_blank("✓")


class TestViolationRule:
    def test_core_rule_fires(self):
        violation, reason = gets_rules.evaluate_violation("✓", "")
        assert violation and "Customer Leave" in reason and "Sacha" in reason

    def test_both_ticked_no_violation(self):
        violation, _ = gets_rules.evaluate_violation("✓", "X")
        assert not violation

    def test_customer_not_ticked_no_violation(self):
        violation, _ = gets_rules.evaluate_violation("", "✓")
        assert not violation

    def test_both_blank_no_violation(self):
        violation, _ = gets_rules.evaluate_violation(None, None)
        assert not violation

    def test_messy_whitespace(self):
        violation, _ = gets_rules.evaluate_violation("  YES  ", " - ")
        assert violation


class TestCheckRowClassification:
    REPO = {
        "e001": {"full_name": "Ann", "official_email": "ann@c.io",
                 "personal_email": "ann@p.io"},
        "e002": {"full_name": "Bob", "official_email": None,
                 "personal_email": "bob@p.io"},
        "e003": {"full_name": "Cid", "official_email": None, "personal_email": None},
    }

    def test_violation_with_official_email(self):
        status, payload = gets_rules.check_row(
            row_values={"employee_code": "E001",
                        "customer_leave": "✓", "sacha_leave": ""},
            repo_lookup=self.REPO,
        )
        assert status == "MATCHED_VIOLATION"
        assert payload["email_to"] == "ann@c.io"  # official wins

    def test_falls_back_to_personal_email(self):
        status, payload = gets_rules.check_row(
            row_values={"employee_code": "E002",
                        "customer_leave": "✓", "sacha_leave": ""},
            repo_lookup=self.REPO,
        )
        assert status == "MATCHED_VIOLATION"
        assert payload["email_to"] == "bob@p.io"

    def test_no_email_flagged_not_sent(self):
        status, payload = gets_rules.check_row(
            row_values={"employee_code": "E003",
                        "customer_leave": "✓", "sacha_leave": ""},
            repo_lookup=self.REPO,
        )
        assert status == "MATCHED_VIOLATION"
        assert payload["email_to"] is None

    def test_employee_not_in_repo_skipped(self):
        status, payload = gets_rules.check_row(
            row_values={"employee_code": "GHOST",
                        "customer_leave": "✓", "sacha_leave": ""},
            repo_lookup=self.REPO,
        )
        assert status == "NOT_IN_REPO"

    def test_missing_columns_detected(self):
        status, _ = gets_rules.check_row(
            row_values={"employee_code": "E001", "extra": {}},
            repo_lookup=self.REPO,
        )
        assert status == "MISSING_COLUMNS"

    def test_bad_id_format(self):
        status, _ = gets_rules.check_row(
            row_values={"employee_code": "!! bad !!",
                        "customer_leave": "✓", "sacha_leave": ""},
            repo_lookup=self.REPO,
        )
        assert status == "BAD_ID_FORMAT"


class TestNormalization:
    HEADERS = ["EMP CODE", " Emp Name ", "Company Email", "Personal Email",
               "Dept", " Customer Leave ", "sacha leave"]

    def test_messy_headers_map_correctly(self):
        from app.services.extraction.normalize import (
            has_leave_columns,
            has_required_columns,
        )

        assert has_required_columns(self.HEADERS)
        assert has_leave_columns(self.HEADERS)

    def test_row_normalization_with_extras(self):
        row = normalize_row(
            self.HEADERS,
            ["E-100", "Dana Smith", "DANA@corp.io ", "dana@gmail.com",
             "Ops", "✓", ""],
        )
        assert row.values["employee_code"] == "E-100"
        assert row.values["full_name"] == "Dana Smith"
        assert row.values["official_email"] == "dana@corp.io"
        assert row.values["personal_email"] == "dana@gmail.com"
        assert row.values["department"] == "Ops"
        assert row.values["customer_leave"] == "✓"
        assert row.values["sacha_leave"] == ""

    def test_invalid_emails_become_none(self):
        row = normalize_row(
            ["Employee ID", "Name", "Official Email"],
            ["E-1", "X Y", "not-an-email"],
        )
        assert row.values["official_email"] is None
