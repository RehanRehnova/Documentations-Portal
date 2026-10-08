"""Write admission rows with the OAuth client id and client secret.

Google does not let a client id and secret call the Sheets API on their own.
The office Google account grants access once. This module keeps the refresh
token (from that grant, or from GOOGLE_REFRESH_TOKEN) and exchanges it for a
short-lived access token on each write.

Create the OAuth client in Google Cloud as a Web application, and register
``{PUBLIC_BASE_URL}/oauth2callback`` as an authorized redirect URI.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import SCOPES, settings
from validation import HEADERS

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

PUBLIC_SAVE_ERROR = (
    "Your application could not be saved just now. Please try again in a few minutes, "
    "or contact the admissions office."
)


class SheetsError(Exception):
    def __init__(self, public_message: str, operator_detail: str):
        super().__init__(operator_detail)
        self.public_message = public_message
        self.operator_detail = operator_detail


def quoted_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _range(cells: str) -> str:
    return f"{quoted_sheet(settings().sheet_name)}!{cells}"


def oauth_client_config() -> dict[str, Any]:
    cfg = settings()
    return {
        "web": {
            "client_id": cfg.google_client_id,
            "client_secret": cfg.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [cfg.redirect_uri],
        }
    }


def authorization_flow(state: str | None = None) -> Flow:
    """Build the web-server OAuth flow.

    PKCE is left off. This app is a confidential client: the client secret is
    sent when the code is exchanged. A new Flow object is created on the
    callback, so pass the original ``state`` there.
    """
    cfg = settings()
    if not cfg.oauth_configured:
        raise SheetsError(
            "Applications are not being accepted online right now. Please contact the admissions office.",
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET before connecting Google.",
        )
    # Google's OAuth helper refuses http:// redirect URIs unless this is set.
    # Leave it unset when PUBLIC_BASE_URL is already https.
    if cfg.public_base_url.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    options: dict[str, Any] = {
        "redirect_uri": cfg.redirect_uri,
        "autogenerate_code_verifier": False,
    }
    if state:
        options["state"] = state
    return Flow.from_client_config(oauth_client_config(), scopes=SCOPES, **options)


def save_credentials(creds: Credentials) -> None:
    cfg = settings()
    cfg.token_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.token_path.write_text(creds.to_json())
    os.chmod(cfg.token_path, 0o600)
    logger.info("Saved Google OAuth token to %s", cfg.token_path)


def load_credentials(*, refresh: bool = True) -> Credentials | None:
    """Return user credentials from GOOGLE_REFRESH_TOKEN or the saved token file."""
    cfg = settings()
    creds: Credentials | None = None
    from_env = False

    if cfg.google_refresh_token:
        if not cfg.oauth_configured:
            return None
        from_env = True
        creds = Credentials(
            token=None,
            refresh_token=cfg.google_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=cfg.google_client_id,
            client_secret=cfg.google_client_secret,
            scopes=SCOPES,
        )
    elif cfg.token_path.exists():
        creds = Credentials.from_authorized_user_file(str(cfg.token_path), SCOPES)
    else:
        return None

    if refresh and creds is not None and creds.refresh_token and not creds.valid:
        creds.refresh(Request())
        if not from_env:
            save_credentials(creds)
    return creds


def _service():
    cfg = settings()
    if not cfg.oauth_configured or not cfg.spreadsheet_configured:
        raise SheetsError(
            "Applications are not being accepted online right now. Please contact the admissions office.",
            "Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and SPREADSHEET_ID.",
        )
    try:
        creds = load_credentials()
    except RefreshError as exc:
        raise SheetsError(
            PUBLIC_SAVE_ERROR,
            "Google refused the stored refresh token. Connect the office account again. "
            f"Detail: {exc}",
        ) from exc
    if creds is None or not creds.valid:
        raise SheetsError(
            "Applications are not being accepted online right now. Please contact the admissions office.",
            "Google is not connected. Open /admin and connect the office Google account, "
            "or set GOOGLE_REFRESH_TOKEN.",
        )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _ensure_tab(service: Any, spreadsheet_id: str, title: str) -> None:
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
        .execute()
    )
    titles = [sheet["properties"]["title"] for sheet in meta.get("sheets", [])]
    if title in titles:
        return
    (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        )
        .execute()
    )
    logger.info("Created worksheet %s", title)


def _ensure_header(service: Any, spreadsheet_id: str) -> None:
    existing = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=_range("1:1"))
        .execute()
        .get("values", [])
    )
    if existing:
        if existing[0] != HEADERS:
            logger.warning(
                "Row 1 of %s does not match the expected header. New rows are still appended.",
                settings().sheet_name,
            )
        return
    (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=_range("A1"),
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        )
        .execute()
    )


def append_application(row: list[str]) -> None:
    """Append one admission to the configured spreadsheet."""
    if len(row) != len(HEADERS):
        raise SheetsError(PUBLIC_SAVE_ERROR, "Internal row width does not match the header.")

    with _write_lock:
        try:
            service = _service()
            spreadsheet_id = settings().spreadsheet_id
            _ensure_tab(service, spreadsheet_id, settings().sheet_name)
            _ensure_header(service, spreadsheet_id)
            result = (
                service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=_range("A1"),
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
                .execute()
            )
        except SheetsError:
            raise
        except HttpError as exc:
            status = getattr(exc.resp, "status", "")
            logger.exception("Google Sheets API error")
            raise SheetsError(
                PUBLIC_SAVE_ERROR,
                f"Google Sheets API returned HTTP {status}.",
            ) from exc
        except RefreshError as exc:
            logger.exception("Google token refresh failed")
            raise SheetsError(
                PUBLIC_SAVE_ERROR,
                f"Google authorization expired or was revoked: {exc}",
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error while writing to Google Sheets")
            raise SheetsError(PUBLIC_SAVE_ERROR, f"Unexpected Sheets error: {exc}") from exc

    updated = result.get("updates", {}).get("updatedRange", "")
    logger.info("Appended admission receipt %s to %s", row[0], updated or settings().sheet_name)


def connection_status() -> dict[str, Any]:
    """Operator-facing check. Does not include secrets."""
    cfg = settings()
    status: dict[str, Any] = {
        "client_id_set": bool(cfg.google_client_id),
        "client_secret_set": bool(cfg.google_client_secret),
        "spreadsheet_id_set": bool(cfg.spreadsheet_id),
        "sheet_name": cfg.sheet_name,
        "redirect_uri": cfg.redirect_uri,
        "refresh_token_set": False,
        "token_valid": False,
        "detail": "",
    }
    try:
        creds = load_credentials(refresh=True)
    except Exception as exc:
        status["detail"] = f"The stored Google token could not be refreshed. Connect again. ({exc.__class__.__name__})"
        logger.warning("Token status check failed: %s", exc)
        return status

    if creds is None:
        status["detail"] = "Google has not been connected yet."
        return status

    status["refresh_token_set"] = bool(creds.refresh_token)
    status["token_valid"] = bool(creds.valid)
    if creds.valid:
        status["detail"] = "Connected. A submitted application will be appended to the sheet."
    elif creds.refresh_token:
        status["detail"] = "A refresh token is stored, but it did not produce a usable access token."
    else:
        status["detail"] = "The saved token has no refresh token. Connect Google again."
    return status
