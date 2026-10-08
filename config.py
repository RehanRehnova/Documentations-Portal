"""Runtime settings for the admission portal.

Values come from the environment and from a local ``.env`` file. Secrets stay
out of source control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

# One scope: append and format rows in spreadsheets this Google account can edit.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

GENDERS = ["Male", "Female", "Other"]

SSC_DEGREES = ["Science", "ICS", "Arts"]

HSSC_DEGREES = ["Pre-engineering", "Pre-medical", "ICS"]

# Written only to the sheet. Pre-engineering and ICS share code 1.
HSSC_DEGREE_CODES = {
    "Pre-engineering": "1",
    "ICS": "1",
    "Pre-medical": "3",
}


@dataclass(frozen=True)
class Settings:
    institution_name: str
    academic_year: str
    public_base_url: str
    port: int
    flask_secret_key: str
    admin_setup_key: str
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    spreadsheet_id: str
    sheet_name: str
    token_path: Path
    trust_proxy: bool

    @property
    def redirect_uri(self) -> str:
        return self.public_base_url.rstrip("/") + "/oauth2callback"

    @property
    def oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def spreadsheet_configured(self) -> bool:
        return bool(self.spreadsheet_id)

    @property
    def admin_configured(self) -> bool:
        key = self.admin_setup_key
        return bool(key) and key.lower() not in {"change-me", "changeme", "secret"}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def normalize_spreadsheet_id(value: str) -> str:
    """Accept a raw spreadsheet id or a full Google Sheets URL."""
    value = value.strip()
    marker = "/spreadsheets/d/"
    if marker in value:
        rest = value.split(marker, 1)[1]
        value = rest.split("/", 1)[0].split("?", 1)[0]
    return value.strip()


@lru_cache
def settings() -> Settings:
    load_dotenv(ROOT / ".env")
    token = _env("TOKEN_PATH")
    token_path = Path(token) if token else ROOT / "data" / "token.json"
    if not token_path.is_absolute():
        token_path = (ROOT / token_path).resolve()
    try:
        port = int(_env("PORT", "8080") or "8080")
    except ValueError:
        port = 8080
    return Settings(
        institution_name=_env("INSTITUTION_NAME", "Admissions Office") or "Admissions Office",
        academic_year=_env("ACADEMIC_YEAR", "2026–27") or "2026–27",
        public_base_url=_env("PUBLIC_BASE_URL", "http://localhost:8080") or "http://localhost:8080",
        port=port,
        flask_secret_key=_env("FLASK_SECRET_KEY"),
        admin_setup_key=_env("ADMIN_SETUP_KEY"),
        google_client_id=_env("GOOGLE_CLIENT_ID"),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
        google_refresh_token=_env("GOOGLE_REFRESH_TOKEN"),
        spreadsheet_id=normalize_spreadsheet_id(_env("SPREADSHEET_ID")),
        sheet_name=_env("SHEET_NAME", "Admissions") or "Admissions",
        token_path=token_path,
        trust_proxy=_env("TRUST_PROXY", "0") == "1",
    )
