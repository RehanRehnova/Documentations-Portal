"""Public student admission form that appends each application to Google Sheets."""

from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict
from datetime import timedelta

from flask import Flask, current_app, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import sheets_client
from config import GENDERS, HSSC_DEGREES, SSC_DEGREES, settings
from sheets_client import SheetsError
from validation import blank_form, mask_cnic, parse_application

logger = logging.getLogger(__name__)

# Modest public limit so one address cannot fill the sheet.
_HITS: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 8
_RATE_WINDOW_SECONDS = 60 * 60


def create_app() -> Flask:
    cfg = settings()
    app = Flask(__name__)
    app.secret_key = cfg.flask_secret_key or "dev-only-set-FLASK_SECRET_KEY"
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = cfg.public_base_url.startswith("https://")
    app.permanent_session_lifetime = timedelta(minutes=30)

    if cfg.trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    if not cfg.flask_secret_key:
        logger.warning("FLASK_SECRET_KEY is empty. Set one before serving this app publicly.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @app.context_processor
    def inject_brand() -> dict[str, str]:
        current = settings()
        return {
            "institution": current.institution_name,
            "academic_year": current.academic_year,
        }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def form():
        return render_template("form.html", **_form_context(blank_form(), {}))

    @app.post("/apply")
    def apply():
        if not _csrf_ok():
            return _message(
                "The form expired",
                "Open the admission form again and submit it once more.",
                url_for("form"),
                "Back to the form",
                400,
            )
        if _too_many(request.remote_addr or "unknown"):
            return _message(
                "Too many applications from this network",
                "Please wait a while and try again, or contact the admissions office.",
                url_for("form"),
                "Back to the form",
                429,
            )

        posted = {key: request.form.get(key, "") for key in request.form}
        application, errors = parse_application(posted)
        if application is None:
            return (
                render_template("form.html", **_form_context(posted, errors)),
                400,
            )

        try:
            sheets_client.append_application(application.as_row())
        except SheetsError as exc:
            logger.error("Admission %s was not saved: %s", application.receipt, exc.operator_detail)
            context = _form_context(posted, {})
            context["notice"] = exc.public_message
            return render_template("form.html", **context), 503

        session["receipt"] = {
            "receipt": application.receipt,
            "submitted_at": application.submitted_at,
            "name": application.name,
            "admission_id": application.admission_id,
            "cnic_masked": mask_cnic(application.cnic),
            "email": application.email,
        }
        session.permanent = True
        return redirect(url_for("success"))

    @app.get("/success")
    def success():
        receipt = session.get("receipt")
        if not receipt:
            return _message(
                "No application on this browser",
                "Submit the admission form and this page will show the receipt.",
                url_for("form"),
                "Go to the form",
                200,
            )
        return render_template("success.html", receipt=receipt)

    @app.route("/admin", methods=["GET", "POST"])
    def admin():
        current = settings()
        if not current.admin_configured:
            return _message(
                "Admin setup is not configured",
                "Set ADMIN_SETUP_KEY in the environment to a long private value, then restart the app.",
                url_for("form"),
                "Back to the form",
                503,
            )
        error = ""
        if request.method == "POST":
            if not _csrf_ok():
                error = "The sign-in form expired. Try again."
            else:
                given = request.form.get("setup_key", "")
                if hmac.compare_digest(given, current.admin_setup_key):
                    session.clear()
                    session["is_admin"] = True
                    session.permanent = True
                    return redirect(url_for("admin"))
                error = "That setup key is not correct."
        if session.get("is_admin"):
            try:
                status = sheets_client.connection_status()
            except Exception as exc:
                logger.exception("Admin status check failed")
                status = {"detail": f"Status check failed: {exc.__class__.__name__}"}
            return render_template(
                "admin.html",
                signed_in=True,
                status=status,
                error="",
                csrf_token=_csrf_token(),
            )
        return render_template(
            "admin.html",
            signed_in=False,
            status=None,
            error=error,
            csrf_token=_csrf_token(),
        )

    @app.post("/admin/logout")
    def admin_logout():
        if _csrf_ok():
            session.clear()
        return redirect(url_for("admin"))

    @app.post("/admin/connect")
    def admin_connect():
        if not session.get("is_admin") or not _csrf_ok():
            return redirect(url_for("admin"))
        try:
            flow = sheets_client.authorization_flow()
        except SheetsError as exc:
            logger.error("OAuth start failed: %s", exc.operator_detail)
            return _message(
                "Google client is not configured",
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then connect again.",
                url_for("admin"),
                "Back to admin",
                503,
            )
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )
        session["oauth_state"] = state
        return redirect(authorization_url)

    @app.get("/oauth2callback")
    def oauth2callback():
        expected = session.get("oauth_state")
        received = request.args.get("state", "")
        if not expected or not received or not hmac.compare_digest(str(expected), received):
            return _message(
                "Google connection was not completed",
                "Start the connection again from the admin page.",
                url_for("admin"),
                "Back to admin",
                400,
            )
        if request.args.get("error"):
            logger.warning("Google OAuth returned an error")
            return _message(
                "Google did not grant access",
                "The office Google account needs to allow this app to edit spreadsheets.",
                url_for("admin"),
                "Back to admin",
                400,
            )
        try:
            flow = sheets_client.authorization_flow(state=received)
            flow.fetch_token(authorization_response=_callback_url())
            sheets_client.save_credentials(flow.credentials)
        except Exception as exc:
            logger.exception("OAuth callback failed")
            return _message(
                "Google connection failed",
                "Check that the redirect URI in Google Cloud matches the one on the admin page, then try again.",
                url_for("admin"),
                "Back to admin",
                400,
            )
        session.pop("oauth_state", None)
        return _message(
            "Google Sheets is connected",
            "New admission forms will be appended to the spreadsheet. Submit a test application to confirm the row.",
            url_for("form"),
            "Open the admission form",
            200,
        )

    @app.errorhandler(404)
    def not_found(_exc):
        return _message(
            "Page not found",
            "That page is not part of the admission form.",
            url_for("form"),
            "Back to the form",
            404,
        )

    @app.errorhandler(413)
    def too_large(_exc):
        return _message(
            "That submission is too large",
            "Shorten the answers and submit the form again.",
            url_for("form"),
            "Back to the form",
            413,
        )

    return app


def _form_context(data: dict, errors: dict[str, str]) -> dict:
    cleaned = blank_form()
    for key in cleaned:
        cleaned[key] = str(data.get(key, "") or "")
    return {
        "data": cleaned,
        "errors": errors,
        "notice": "",
        "genders": GENDERS,
        "ssc_degrees": SSC_DEGREES,
        "hssc_degrees": HSSC_DEGREES,
        "csrf_token": _csrf_token(),
    }


def _csrf_token() -> str:
    import secrets

    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _csrf_ok() -> bool:
    sent = request.form.get("csrf_token", "")
    saved = session.get("csrf_token", "")
    if not sent or not saved:
        return False
    return hmac.compare_digest(sent, saved)


def _too_many(ip: str) -> bool:
    if current_app.config.get("TESTING"):
        return False
    now = time.monotonic()
    recent = [stamp for stamp in _HITS[ip] if now - stamp < _RATE_WINDOW_SECONDS]
    if len(recent) >= _RATE_LIMIT:
        _HITS[ip] = recent
        return True
    recent.append(now)
    _HITS[ip] = recent
    return False


def _callback_url() -> str:
    """Rebuild the redirect URL from PUBLIC_BASE_URL so it matches Google Cloud."""
    query = request.query_string.decode("utf-8")
    base = settings().redirect_uri
    return f"{base}?{query}" if query else base


def _message(title: str, body: str, next_href: str, next_label: str, status: int):
    return (
        render_template(
            "message.html",
            title=title,
            body=body,
            next_href=next_href,
            next_label=next_label,
        ),
        status,
    )


app = create_app()


if __name__ == "__main__":
    current = settings()
    app.run(host="0.0.0.0", port=8080)
