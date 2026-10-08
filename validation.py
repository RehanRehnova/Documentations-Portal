"""Turn a submitted student information form into one spreadsheet row.

The server checks every field again. Browser checks are only a convenience.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping
from zoneinfo import ZoneInfo

from config import GENDERS, HSSC_DEGREE_CODES, HSSC_DEGREES, SSC_DEGREES

PKT = ZoneInfo("Asia/Karachi")

HEADERS = [
    "Receipt No",
    "Submitted At",
    "Name",
    "Father's Name",
    "Gender",
    "Date of Birth",
    "CNIC Number",
    "Nationality",
    "Admission ID",
    "Admission Date",
    "Phone Number",
    "Email Address",
    "Mailing Address",
    "City Mailing Address",
    "Domicile District",
    "Domicile Province",
    "SSC Degree",
    "SSC Board",
    "SSC Total Marks",
    "SSC Obtained Marks",
    "HSSC Degree",
    "HSSC Degree 2",
    "HSSC Board",
    "HSSC Total Marks",
    "HSSC Obtained Marks",
]

EMAIL_WARNING = (
    "This is not an email address. Enter an email address. "
    "Suggested email addresses are Gmail, Proton, or whatever mail anyone likes to add."
)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

FORM_FIELDS = [
    "name",
    "father_name",
    "gender",
    "date_of_birth",
    "cnic",
    "nationality",
    "admission_id",
    "admission_date",
    "phone",
    "email",
    "mailing_address",
    "city",
    "domicile_district",
    "domicile_province",
    "ssc_degree",
    "ssc_board",
    "ssc_total_marks",
    "ssc_obtained_marks",
    "hssc_degree",
    "hssc_board",
    "hssc_total_marks",
    "hssc_obtained_marks",
    "declaration",
]


def blank_form() -> dict[str, str]:
    return {name: "" for name in FORM_FIELDS}


def now_pkt() -> datetime:
    return datetime.now(PKT)


def new_receipt(moment: datetime | None = None) -> str:
    stamp = (moment or now_pkt()).strftime("%Y%m%d")
    return f"ADM-{stamp}-{secrets.token_hex(3).upper()}"


def sheet_safe(value: str) -> str:
    """Stop a cell that starts with =, +, -, or @ from running as a formula."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def mask_cnic(cnic: str) -> str:
    if len(cnic) == 13 and cnic.isdigit():
        return cnic[:5] + "*******" + cnic[-1:]
    if len(cnic) < 8:
        return cnic
    return cnic[:5] + "****" + cnic[-2:]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _letters(value: str) -> int:
    return sum(1 for char in value if char.isalpha())


def _person_name(value: str) -> bool:
    if not 2 <= len(value) <= 80 or _letters(value) < 2:
        return False
    return all(char.isalpha() or char in " .'()-" for char in value)


def _words(value: str, low: int, high: int) -> bool:
    if not low <= len(value) <= high or _letters(value) < 2:
        return False
    return all(char.isalpha() or char in " -" for char in value)


def _place(value: str, high: int) -> bool:
    if not 2 <= len(value) <= high or _letters(value) < 2:
        return False
    return all(char.isalnum() or char in " .'-,&" for char in value)


def _cnic_error(value: str) -> str:
    if not value:
        return "Enter the CNIC number. It must be exactly 13 numbers."
    if not value.isdigit():
        return "Enter exactly 13 numbers. Letters, dashes, and spaces are not allowed."
    if len(value) < 13:
        return "Enter exactly 13 numbers. This CNIC has fewer than 13 numbers."
    if len(value) > 13:
        return "Enter exactly 13 numbers. This CNIC has more than 13 numbers."
    return ""


def _phone(value: str) -> tuple[str, str]:
    if not value:
        return "", "Enter a phone number, for example 03001234567."
    if re.search(r"[A-Za-z]", value):
        return "", "This is not a phone number. Use digits, for example 03001234567."
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return "", "This phone number is too short. Enter at least 10 digits, for example 03001234567."
    if len(digits) > 15:
        return "", "This phone number is too long. Enter at most 15 digits."
    stored = "+" + digits if value.startswith("+") else digits
    return stored, ""


def _whole_marks(value: str, label: str, *, allow_zero: bool) -> tuple[str, str]:
    if not re.fullmatch(r"\d+", value or ""):
        return "", f"Enter {label} as a whole number, without letters or decimals."
    number = int(value)
    upper = 9999
    if allow_zero:
        if number > upper:
            return "", f"Enter {label} as a whole number from 0 to {upper}."
    elif not 1 <= number <= upper:
        return "", f"Enter {label} as a whole number from 1 to {upper}."
    return str(number), ""


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _age(born: date, today: date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


@dataclass(frozen=True)
class Application:
    receipt: str
    submitted_at: str
    name: str
    father_name: str
    gender: str
    date_of_birth: str
    cnic: str
    nationality: str
    admission_id: str
    admission_date: str
    phone: str
    email: str
    mailing_address: str
    city: str
    domicile_district: str
    domicile_province: str
    ssc_degree: str
    ssc_board: str
    ssc_total_marks: str
    ssc_obtained_marks: str
    hssc_degree: str
    hssc_board: str
    hssc_total_marks: str
    hssc_obtained_marks: str

    def as_row(self) -> list[str]:
        row = [
            self.receipt,
            self.submitted_at,
            self.name,
            self.father_name,
            self.gender,
            self.date_of_birth,
            self.cnic,
            self.nationality,
            self.admission_id,
            self.admission_date,
            self.phone,
            self.email,
            self.mailing_address,
            self.city,
            self.domicile_district,
            self.domicile_province,
            self.ssc_degree,
            self.ssc_board,
            self.ssc_total_marks,
            self.ssc_obtained_marks,
            self.hssc_degree,
            HSSC_DEGREE_CODES[self.hssc_degree],
            self.hssc_board,
            self.hssc_total_marks,
            self.hssc_obtained_marks,
        ]
        safe = [sheet_safe(cell) for cell in row]
        if len(safe) != len(HEADERS):
            raise RuntimeError("Application row does not match the sheet header.")
        return safe


def parse_application(
    form: Mapping[str, str],
    *,
    moment: datetime | None = None,
) -> tuple[Application | None, dict[str, str]]:
    raw = {name: _clean(str(form.get(name, ""))) for name in FORM_FIELDS}
    raw["declaration"] = str(form.get("declaration", "")).strip()
    raw["email"] = raw["email"].strip()
    errors: dict[str, str] = {}

    if not _person_name(raw["name"]):
        errors["name"] = "Enter the student's name in letters."
    if not _person_name(raw["father_name"]):
        errors["father_name"] = "Enter the father's name in letters."
    if raw["gender"] not in GENDERS:
        errors["gender"] = "Select a gender: Male, Female, or Other."

    moment = moment or now_pkt()
    today = moment.date()
    admission = _parse_date(raw["admission_date"])
    if admission is None:
        errors["admission_date"] = "Enter a valid admission date."
    elif admission.year < 1990 or admission > today + timedelta(days=366):
        errors["admission_date"] = "Enter an admission date from 1990 up to one year from today."

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-/]{1,39}", raw["admission_id"]):
        errors["admission_id"] = "Enter the admission ID using letters, numbers, or a hyphen."

    if not _words(raw["nationality"], 2, 40):
        errors["nationality"] = "Enter a nationality in letters, for example Pakistani."

    cnic_error = _cnic_error(raw["cnic"])
    if cnic_error:
        errors["cnic"] = cnic_error

    born = _parse_date(raw["date_of_birth"])
    if born is None:
        errors["date_of_birth"] = "Enter a valid date of birth."
    else:
        age = _age(born, today)
        if born > today or age < 14 or age > 80:
            errors["date_of_birth"] = "Enter a real date of birth. The student must be 14 to 80 years old."
        elif admission is not None and born >= admission:
            errors["date_of_birth"] = "Date of birth must be before the admission date."

    phone, phone_error = _phone(raw["phone"])
    if phone_error:
        errors["phone"] = phone_error

    email = raw["email"]
    if not EMAIL_RE.fullmatch(email) or len(email) > 254:
        errors["email"] = EMAIL_WARNING
    else:
        email = email.lower()

    if not 8 <= len(raw["mailing_address"]) <= 300 or _letters(raw["mailing_address"]) < 3:
        errors["mailing_address"] = "Enter the mailing address in words. Numbers alone are not enough."
    if not _place(raw["city"], 60):
        errors["city"] = "Enter the city mailing address in letters."

    if raw["ssc_degree"] not in SSC_DEGREES:
        errors["ssc_degree"] = "Select an SSC degree: Science, ICS, or Arts."
    if not _place(raw["ssc_board"], 80):
        errors["ssc_board"] = "Enter the SSC board name."

    ssc_total, ssc_total_error = _whole_marks(raw["ssc_total_marks"], "SSC total marks", allow_zero=False)
    ssc_obtained, ssc_obtained_error = _whole_marks(
        raw["ssc_obtained_marks"], "SSC obtained marks", allow_zero=True
    )
    if ssc_total_error:
        errors["ssc_total_marks"] = ssc_total_error
    if ssc_obtained_error:
        errors["ssc_obtained_marks"] = ssc_obtained_error
    elif ssc_total and int(ssc_obtained) > int(ssc_total):
        errors["ssc_obtained_marks"] = "SSC obtained marks cannot be more than the SSC total marks."

    if raw["hssc_degree"] not in HSSC_DEGREES:
        errors["hssc_degree"] = "Select an HSSC degree: Pre-engineering, Pre-medical, or ICS."
    if not _place(raw["hssc_board"], 80):
        errors["hssc_board"] = "Enter the HSSC board name."

    hssc_total, hssc_total_error = _whole_marks(raw["hssc_total_marks"], "HSSC total marks", allow_zero=False)
    hssc_obtained, hssc_obtained_error = _whole_marks(
        raw["hssc_obtained_marks"], "HSSC obtained marks", allow_zero=True
    )
    if hssc_total_error:
        errors["hssc_total_marks"] = hssc_total_error
    if hssc_obtained_error:
        errors["hssc_obtained_marks"] = hssc_obtained_error
    elif hssc_total and int(hssc_obtained) > int(hssc_total):
        errors["hssc_obtained_marks"] = "HSSC obtained marks cannot be more than the HSSC total marks."

    if not _place(raw["domicile_district"], 60):
        errors["domicile_district"] = "Enter the domicile district in letters."
    if not _place(raw["domicile_province"], 40):
        errors["domicile_province"] = "Enter the domicile province in letters."

    if raw["declaration"] != "yes":
        errors["declaration"] = "Confirm that the information is correct."

    if errors:
        return None, errors

    application = Application(
        receipt=new_receipt(moment),
        submitted_at=moment.strftime("%Y-%m-%d %H:%M:%S"),
        name=raw["name"],
        father_name=raw["father_name"],
        gender=raw["gender"],
        date_of_birth=raw["date_of_birth"],
        cnic=raw["cnic"],
        nationality=raw["nationality"],
        admission_id=raw["admission_id"],
        admission_date=raw["admission_date"],
        phone=phone,
        email=email,
        mailing_address=raw["mailing_address"],
        city=raw["city"],
        domicile_district=raw["domicile_district"],
        domicile_province=raw["domicile_province"],
        ssc_degree=raw["ssc_degree"],
        ssc_board=raw["ssc_board"],
        ssc_total_marks=ssc_total,
        ssc_obtained_marks=ssc_obtained,
        hssc_degree=raw["hssc_degree"],
        hssc_board=raw["hssc_board"],
        hssc_total_marks=hssc_total,
        hssc_obtained_marks=hssc_obtained,
    )
    return application, {}
