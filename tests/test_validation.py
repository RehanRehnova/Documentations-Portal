from datetime import datetime

from config import normalize_spreadsheet_id
from sheets_client import quoted_sheet
from validation import EMAIL_WARNING, PKT, parse_application, sheet_safe


MOMENT = datetime(2026, 10, 8, 15, 4, tzinfo=PKT)


def payload(**overrides) -> dict[str, str]:
    data = {
        "name": "Ayesha Khan",
        "father_name": "Imran Khan",
        "gender": "Female",
        "admission_date": "2026-09-01",
        "admission_id": "ADM-2041",
        "nationality": "Pakistani",
        "cnic": "4210112345671",
        "date_of_birth": "2004-05-12",
        "phone": "+92 300 1234567",
        "email": "Ayesha@Example.com",
        "mailing_address": "=House 12, Block C, Gulshan",
        "city": "Karachi",
        "ssc_degree": "Science",
        "ssc_board": "BISE Karachi",
        "ssc_total_marks": "1100",
        "ssc_obtained_marks": "980",
        "hssc_degree": "Pre-engineering",
        "hssc_board": "BISE Karachi",
        "hssc_total_marks": "1100",
        "hssc_obtained_marks": "912",
        "domicile_district": "Karachi East",
        "domicile_province": "Sindh",
        "declaration": "yes",
    }
    data.update(overrides)
    return data


def test_valid_application_keeps_13_digit_cnic_and_writes_every_column():
    application, errors = parse_application(payload(), moment=MOMENT)
    assert errors == {}
    assert application is not None
    assert application.cnic == "4210112345671"
    assert application.phone == "+923001234567"
    assert application.email == "ayesha@example.com"
    row = application.as_row()
    assert len(row) == 25
    assert row[2] == "Ayesha Khan"
    assert row[6] == "4210112345671"
    assert row[8] == "ADM-2041"
    assert row[12].startswith("'=")
    assert row[16] == "Science"
    assert row[20] == "Pre-engineering"
    assert row[21] == "1"


def test_hssc_codes_are_one_for_engineering_and_ics_and_three_for_medical():
    engineering, _ = parse_application(payload(hssc_degree="Pre-engineering"), moment=MOMENT)
    ics, _ = parse_application(payload(hssc_degree="ICS"), moment=MOMENT)
    medical, _ = parse_application(payload(hssc_degree="Pre-medical"), moment=MOMENT)
    assert engineering is not None and engineering.as_row()[20:22] == ["Pre-engineering", "1"]
    assert ics is not None and ics.as_row()[20:22] == ["ICS", "1"]
    assert medical is not None and medical.as_row()[20:22] == ["Pre-medical", "3"]


def test_email_numbers_and_plain_words_are_rejected():
    for bad in ("12345", "ayesha", "student@", "name@gmail"):
        _, errors = parse_application(payload(email=bad), moment=MOMENT)
        assert errors["email"] == EMAIL_WARNING


def test_cnic_must_be_exactly_13_digits():
    short, short_errors = parse_application(payload(cnic="421011234567"), moment=MOMENT)
    long, long_errors = parse_application(payload(cnic="42101123456711"), moment=MOMENT)
    dashed, dashed_errors = parse_application(payload(cnic="42101-1234567-1"), moment=MOMENT)
    assert short is None and long is None and dashed is None
    assert "fewer than 13" in short_errors["cnic"]
    assert "more than 13" in long_errors["cnic"]
    assert "Letters, dashes" in dashed_errors["cnic"]


def test_obtained_marks_cannot_exceed_the_total():
    _, errors = parse_application(payload(ssc_obtained_marks="1200"), moment=MOMENT)
    assert "cannot be more than" in errors["ssc_obtained_marks"]


def test_sheet_formula_prefix_and_sheet_title_quoting():
    assert sheet_safe("=cmd") == "'=cmd"
    assert sheet_safe("Ayesha") == "Ayesha"
    assert quoted_sheet("Admissions") == "'Admissions'"
    assert quoted_sheet("Year's Intake") == "'Year''s Intake'"


def test_spreadsheet_id_can_be_pasted_as_a_url():
    url = "https://docs.google.com/spreadsheets/d/abc123_XYZ/edit#gid=0"
    assert normalize_spreadsheet_id(url) == "abc123_XYZ"
    assert normalize_spreadsheet_id(" plain-id ") == "plain-id"
