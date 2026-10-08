# Student admission form

A public web form for student admissions. Each submission is appended as a row in a Google Sheet.

The sheet is written with an OAuth **client ID** and **client secret**. The office Google account grants access once. After that, the app keeps a refresh token and uses it to add rows. Students never see the Google account or the secret.

## What the form asks for

Name, Father's Name, Gender, Date of Birth, CNIC Number, Nationality, Admission ID, Admission Date, Phone Number, Email Address, Mailing Address, City Mailing Address, Domicile District, Domicile Province, SSC Degree, SSC Board, SSC Total Marks, SSC Obtained Marks, HSSC Degree, HSSC Board, HSSC Total Marks, and HSSC Obtained Marks.

A receipt number is shown after a successful save. The CNIC on that page is masked. The spreadsheet receives the full CNIC.

## Project layout

- `app.py` serves the form and the one-time Google connection
- `validation.py` checks the submission
- `sheets_client.py` talks to Google Sheets
- `templates/` and `static/` are the page
- `.env` holds the client id, client secret, and spreadsheet id

## 1. Install

```bash
cd student-admission
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`. Set `FLASK_SECRET_KEY` and `ADMIN_SETUP_KEY` to long random strings. Set `INSTITUTION_NAME` to the college name.

SSC Degree choices are Science, ICS, and Arts. HSSC Degree choices are Pre-engineering, Pre-medical, and ICS. The sheet also gets an HSSC Degree 2 column: 1 for Pre-engineering and ICS, 3 for Pre-medical. Both lists are in `config.py`.

## 2. Create the Google OAuth client

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Enable the **Google Sheets API** for that project (APIs & Services → Library).
3. Open **Google Auth platform** / **OAuth consent screen**.
   - User type: External.
   - App name: something the office will recognize, such as "Admission form".
   - Add the scope `https://www.googleapis.com/auth/spreadsheets`.
   - Add the office Google account under **Test users** if the app stays in Testing.
4. Create a client: APIs & Services → Credentials → Create credentials → **OAuth client ID**.
   - Application type: **Web application**.
   - Authorized redirect URI: the value of `PUBLIC_BASE_URL` plus `/oauth2callback`.
   - For this machine that is `http://localhost:8080/oauth2callback` unless you change the port or the public URL.
5. Copy the client ID and client secret into `.env`:

```bash
GOOGLE_CLIENT_ID="your-id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your-secret"
```

6. Create an empty Google Sheet while signed in as that same office account. Copy the spreadsheet id from the URL:

```text
https://docs.google.com/spreadsheets/d/<spreadsheet id>/edit
```

Put it in `SPREADSHEET_ID`. A full spreadsheet URL is also accepted. The worksheet named in `SHEET_NAME` (default `Admissions`) is created on the first submission if it is missing. The header row is written when row 1 is empty.

## 3. Connect the office Google account

The client id and secret identify the app. Google still requires the office account to approve spreadsheet access once.

```bash
python app.py
```

The form listens on all interfaces, port 8080 by default.

1. Open `http://localhost:8080/admin`.
2. Enter `ADMIN_SETUP_KEY`.
3. Copy the redirect URI shown on that page into the OAuth client if it is not there already.
4. Choose **Connect Google account** and sign in as the account that owns the sheet.
5. When the browser returns, the refresh token is stored in `data/token.json`. That file is private to the server. Do not commit it.

You can instead paste a refresh token into `GOOGLE_REFRESH_TOKEN` and skip the browser step. Leave it blank to use `data/token.json`.

While the OAuth app is in **Testing**, Google expires refresh tokens after 7 days. Publish the consent screen to **In production** so the office does not have to reconnect every week. The first time, Google may show an "unverified app" warning. The office account can continue from the advanced prompt. This app only requests the spreadsheets scope.

## 4. Serve it publicly

On the server:

```bash
chmod +x serve.sh
./serve.sh
```

That runs gunicorn on `0.0.0.0` and the port in `.env`. Open the firewall for that port. One network address can submit 8 applications an hour.

Set `PUBLIC_BASE_URL` to the URL students will use, for example `https://admissions.example.edu`. The redirect URI registered in Google Cloud must be exactly `{PUBLIC_BASE_URL}/oauth2callback`. Restart, then connect Google again from `/admin` if the redirect URI changed.

Put HTTPS in front of the app (Caddy, nginx, or the host's load balancer). When a proxy forwards the original host and protocol, set `TRUST_PROXY=1`.

A local check that does not need Google:

```bash
pytest
```

`GET /health` returns `{"status": "ok"}`.

## Columns written to the sheet

Receipt No, Submitted At (Asia/Karachi), then the 22 student fields in form order: Name, Father's Name, Gender, Date of Birth, CNIC Number, Nationality, Admission ID, Admission Date, Phone Number, Email Address, Mailing Address, City Mailing Address, Domicile District, Domicile Province, SSC Degree, SSC Board, SSC Total Marks, SSC Obtained Marks, HSSC Degree, HSSC Degree 2, HSSC Board, HSSC Total Marks, HSSC Obtained Marks.

Values that start with `=`, `+`, `-`, or `@` are prefixed so Google Sheets does not treat them as formulas.

## Environment

| Variable | Purpose |
| --- | --- |
| `INSTITUTION_NAME` | Name shown on the form |
| `ACADEMIC_YEAR` | Year shown in the header |
| `PUBLIC_BASE_URL` | Public origin, no trailing path |
| `PORT` | Port to bind |
| `FLASK_SECRET_KEY` | Signs the browser session |
| `ADMIN_SETUP_KEY` | Password for `/admin` |
| `GOOGLE_CLIENT_ID` | OAuth web client id |
| `GOOGLE_CLIENT_SECRET` | OAuth web client secret |
| `GOOGLE_REFRESH_TOKEN` | Optional token from a previous grant |
| `SPREADSHEET_ID` | Sheet id or full sheet URL |
| `SHEET_NAME` | Worksheet tab name |
| `TRUST_PROXY` | Set to `1` behind a reverse proxy |

## Troubleshooting

- **Redirect URI mismatch.** The URI on `/admin` and the URI in Google Cloud must be identical, including `http` or `https` and the port.
- **Applications are not being accepted.** The client id, client secret, spreadsheet id, or Google connection is missing. `/admin` shows which one.
- **Token refresh failed after a week.** The consent screen is still in Testing. Publish it to production, then connect again.
- **Google Sheets API returned HTTP 403.** Enable the Sheets API, and connect the Google account that can edit the spreadsheet.
- **HTTP 404 on the callback.** `PUBLIC_BASE_URL` does not point at this app.
