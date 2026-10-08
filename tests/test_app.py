import re
from pathlib import Path

import pytest

from config import settings


@pytest.fixture
def clean_settings(monkeypatch, tmp_path):
    token_path = tmp_path / "token.json"
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ADMIN_SETUP_KEY", "test-admin-key")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SPREADSHEET_ID", "sheet-id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "")
    monkeypatch.setenv("SHEET_NAME", "Admissions")
    monkeypatch.setenv("INSTITUTION_NAME", "Test College")
    monkeypatch.setenv("TOKEN_PATH", str(token_path))
    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.fixture
def client(clean_settings):
    from app import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application.test_client()


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def valid_form(token: str) -> dict[str, str]:
    return {
        "csrf_token": token,
        "name": "Ayesha Khan",
        "father_name": "Imran Khan",
        "gender": "Female",
        "admission_date": "2026-09-01",
        "admission_id": "ADM-2041",
        "nationality": "Pakistani",
        "cnic": "4210112345671",
        "date_of_birth": "2004-05-12",
        "phone": "03001234567",
        "email": "ayesha@gmail.com",
        "mailing_address": "House 12, Block C, Gulshan",
        "city": "Karachi",
        "ssc_degree": "Science",
        "ssc_board": "BISE Karachi",
        "ssc_total_marks": "1100",
        "ssc_obtained_marks": "980",
        "hssc_degree": "Pre-medical",
        "hssc_board": "BISE Karachi",
        "hssc_total_marks": "1100",
        "hssc_obtained_marks": "912",
        "domicile_district": "Karachi East",
        "domicile_province": "Sindh",
        "declaration": "yes",
    }


def test_oauth_url_uses_the_client_secret_flow(clean_settings):
    from sheets_client import authorization_flow

    flow = authorization_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    assert url.startswith("https://accounts.google.com/o/oauth2/auth?")
    assert "client_id=client-id.apps.googleusercontent.com" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Foauth2callback" in url
    assert "access_type=offline" in url
    assert "code_challenge" not in url
    assert state


def test_form_page_is_public(client):
    response = client.get("/")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Student Information" in page
    assert "Test College" in page
    assert page.index(">Name</label>") < page.index(">Father's Name</label>")
    assert page.index(">Father's Name</label>") < page.index(">Domicile Province</label>")
    assert ">Male</option>" in page
    assert ">Female</option>" in page
    assert ">Other</option>" in page
    assert page.index(">Male</option>") < page.index(">Female</option>") < page.index(">Other</option>")
    assert ">Science</option>" in page
    assert ">ICS</option>" in page
    assert ">Arts</option>" in page
    assert ">Pre-engineering</option>" in page
    assert ">Pre-medical</option>" in page
    assert ">Diploma Holder</option>" not in page
    assert 'id="submit-btn" disabled' in page


def test_invalid_submission_explains_the_cnic(client):
    token = csrf_from(client.get("/").get_data(as_text=True))
    body = valid_form(token)
    body["cnic"] = "12345"
    body["email"] = "12345"
    response = client.post("/apply", data=body)
    page = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "fewer than 13" in page
    assert "This is not an email address" in page


def test_missing_csrf_is_rejected(client):
    response = client.post("/apply", data=valid_form("wrong-token"))
    assert response.status_code == 400


def test_valid_submission_appends_a_row_and_shows_a_receipt(client, monkeypatch):
    stored = {}

    def fake_append(row):
        stored["row"] = row

    monkeypatch.setattr("app.sheets_client.append_application", fake_append)
    token = csrf_from(client.get("/").get_data(as_text=True))
    response = client.post("/apply", data=valid_form(token))
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/success")
    assert stored["row"][2] == "Ayesha Khan"
    assert stored["row"][6] == "4210112345671"
    assert stored["row"][8] == "ADM-2041"
    assert stored["row"][20] == "Pre-medical"
    assert stored["row"][21] == "3"
    receipt = client.get("/success")
    page = receipt.get_data(as_text=True)
    assert "Keep this receipt number" in page
    assert "42101*******1" in page
    assert "4210112345671" not in page


def test_unconfigured_sheet_does_not_crash(client):
    token = csrf_from(client.get("/").get_data(as_text=True))
    response = client.post("/apply", data=valid_form(token))
    assert response.status_code == 503
    assert "admissions office" in response.get_data(as_text=True).lower()


def test_admin_key_and_oauth_redirect(client, monkeypatch, tmp_path):
    page = client.get("/admin")
    assert page.status_code == 200
    token = csrf_from(page.get_data(as_text=True))
    denied = client.post("/admin", data={"csrf_token": token, "setup_key": "nope"})
    assert "not correct" in denied.get_data(as_text=True)

    allowed = client.post("/admin", data={"csrf_token": token, "setup_key": "test-admin-key"})
    assert allowed.status_code == 302
    status = client.get("/admin")
    body = status.get_data(as_text=True)
    assert "http://localhost:8080/oauth2callback" in body
    assert "client-secret" not in body

    class FakeFlow:
        def authorization_url(self, **kwargs):
            assert kwargs["access_type"] == "offline"
            return "https://accounts.google.com/o/oauth2/auth?client_id=x", "state-123"

    monkeypatch.setattr("app.sheets_client.authorization_flow", lambda: FakeFlow())
    connect_token = csrf_from(body)
    started = client.post("/admin/connect", data={"csrf_token": connect_token})
    assert started.status_code == 302
    assert started.headers["Location"].startswith("https://accounts.google.com/")

    class Saved:
        def to_json(self):
            return '{"refresh_token":"refresh","token":"access"}'

    class CallbackFlow:
        credentials = Saved()

        def fetch_token(self, authorization_response):
            assert "code=abc" in authorization_response
            assert authorization_response.startswith("http://localhost:8080/oauth2callback?")

    monkeypatch.setattr(
        "app.sheets_client.authorization_flow",
        lambda state=None: CallbackFlow(),
    )
    with client.session_transaction() as sess:
        sess["oauth_state"] = "state-123"
    callback = client.get("/oauth2callback?code=abc&state=state-123")
    assert callback.status_code == 200
    assert "Google Sheets is connected" in callback.get_data(as_text=True)
    saved = Path(settings().token_path).read_text()
    assert "refresh" in saved
    assert oct(Path(settings().token_path).stat().st_mode & 0o777) == "0o600"
