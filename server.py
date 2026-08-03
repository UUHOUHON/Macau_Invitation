"""
Dinner invitation server — emails guest details and booking confirmations.
"""

import json
import os
import re
import socket
import smtplib
import ssl
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "houhonuhh@gmail.com").strip()
HOST_NOTIFY_EMAIL = os.environ.get("HOST_NOTIFY_EMAIL", SENDER_EMAIL).strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM = os.environ.get(
    "RESEND_FROM", "Dinner Invitation <onboarding@resend.dev>"
).strip()
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()

APP_NAME = "Dinner Invitation"

GUEST_EMAIL_HELP = (
    "Resend free plan only sends to houhonuhh@gmail.com. "
    "To email any address: sign up free at brevo.com → verify houhonuhh@gmail.com as sender "
    "→ add BREVO_API_KEY in Render Environment → Save and redeploy."
)

app = Flask(__name__, static_folder=".")

APP_PASSWORD_HELP = (
    "Email is not configured. Set GMAIL_APP_PASSWORD (16-char Google App Password) "
    "for local use, or RESEND_API_KEY from resend.com for Render hosting."
)

RENDER_SMTP_HELP = (
    "Gmail SMTP is blocked on Render (network unreachable). "
    "Sign up free at https://resend.com → API Keys → add RESEND_API_KEY in "
    "Render Environment → Save and redeploy."
)

PHONE_RE = re.compile(r"[^\d+]")


def _gmail_auth_error_message(exc: smtplib.SMTPAuthenticationError) -> str:
    detail = (exc.smtp_error or b"").decode(errors="ignore").lower()
    if "application-specific password" in detail or exc.smtp_code == 534:
        if len(GMAIL_APP_PASSWORD) < 16:
            return APP_PASSWORD_HELP
        return (
            "Gmail rejected the App Password. Create a new one at "
            "https://myaccount.google.com/apppasswords and update GMAIL_APP_PASSWORD."
        )
    return "Gmail login failed. Check SENDER_EMAIL and GMAIL_APP_PASSWORD."


def _smtp_host_ipv4(host: str, port: int) -> str:
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    return infos[0][4][0]


def send_via_gmail(recipient: str, subject: str, body: str, html_body: str | None = None) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((APP_NAME, SENDER_EMAIL))
    msg["To"] = recipient
    msg["Reply-To"] = SENDER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    raw = msg.as_string()
    context = ssl.create_default_context()
    last_auth_error = None
    last_network_error = None

    try:
        host_ip = _smtp_host_ipv4("smtp.gmail.com", 587)
        with smtplib.SMTP(host_ip, 587, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [recipient], raw)
            return
    except smtplib.SMTPAuthenticationError as exc:
        last_auth_error = exc
    except OSError as exc:
        last_network_error = exc

    try:
        host_ip = _smtp_host_ipv4("smtp.gmail.com", 465)
        with smtplib.SMTP_SSL(host_ip, 465, context=context, timeout=30) as server:
            server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [recipient], raw)
            return
    except smtplib.SMTPAuthenticationError as exc:
        last_auth_error = exc
    except OSError as exc:
        last_network_error = exc

    if last_auth_error:
        raise last_auth_error
    if last_network_error:
        raise last_network_error
    raise RuntimeError("Could not connect to Gmail SMTP.")


def _parse_resend_error(detail: str, status: int) -> str:
    try:
        data = json.loads(detail)
        msg = data.get("message", detail)
        if status == 403 and "verify a domain" in msg.lower():
            return (
                "Resend free plan can only email houhonuhh@gmail.com until you verify a domain. "
                "Go to resend.com/domains to add one, or use your Gmail as the notify address."
            )
        return f"Resend: {msg}"
    except json.JSONDecodeError:
        if "1010" in detail:
            return "Resend connection blocked. Redeploy after the latest update (User-Agent fix)."
        return f"Resend error: {detail[:200]}"


def _resend_sandbox() -> bool:
    return "onboarding@resend.dev" in RESEND_FROM.lower()


def send_via_brevo(recipient: str, subject: str, body: str, html_body: str | None = None) -> None:
    payload = json.dumps(
        {
            "sender": {"name": APP_NAME, "email": SENDER_EMAIL},
            "to": [{"email": recipient}],
            "replyTo": {"email": SENDER_EMAIL},
            "subject": subject,
            "textContent": body,
            "htmlContent": html_body or body.replace("\n", "<br>"),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "dinner-invitation/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"Brevo returned status {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")
        try:
            msg = json.loads(detail).get("message", detail)
        except json.JSONDecodeError:
            msg = detail[:200]
        raise RuntimeError(f"Brevo: {msg}") from exc


def send_via_resend(recipient: str, subject: str, body: str, html_body: str | None = None) -> None:
    payload = json.dumps(
        {
            "from": RESEND_FROM,
            "to": [recipient],
            "reply_to": SENDER_EMAIL,
            "subject": subject,
            "text": body,
            "html": html_body or body.replace("\n", "<br>"),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "dinner-invitation/1.0 (Render)",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"Resend returned status {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")
        raise RuntimeError(_parse_resend_error(detail, exc.code)) from exc


def send_email(recipient: str, subject: str, body: str, html_body: str | None = None) -> str:
    """Send email. Returns provider name used."""
    on_render = bool(os.environ.get("RENDER"))

    if BREVO_API_KEY:
        send_via_brevo(recipient, subject, body, html_body)
        return "brevo"

    if RESEND_API_KEY:
        if _resend_sandbox() and recipient.lower() != SENDER_EMAIL.lower():
            raise RuntimeError(GUEST_EMAIL_HELP)
        send_via_resend(recipient, subject, body, html_body)
        return "resend"

    if not GMAIL_APP_PASSWORD or len(GMAIL_APP_PASSWORD) < 16:
        raise ValueError(APP_PASSWORD_HELP)

    try:
        send_via_gmail(recipient, subject, body, html_body)
        return "gmail"
    except OSError as exc:
        if on_render or getattr(exc, "errno", None) == 101:
            raise RuntimeError(RENDER_SMTP_HELP) from exc
        raise


def _normalize_phone(raw: str) -> str:
    cleaned = PHONE_RE.sub("", (raw or "").strip())
    if cleaned.count("+") > 1:
        cleaned = "+" + cleaned.replace("+", "")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


def _phone_looks_valid(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return 8 <= len(digits) <= 15


def _email_looks_valid(email: str) -> bool:
    email = (email or "").strip()
    if "@" not in email or " " in email:
        return False
    local, _, domain = email.partition("@")
    return bool(local) and "." in domain and len(email) <= 254


def _email_ready() -> bool:
    return bool(BREVO_API_KEY) or bool(RESEND_API_KEY) or len(GMAIL_APP_PASSWORD) >= 16


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/email-status", methods=["GET"])
def email_status():
    has_brevo = bool(BREVO_API_KEY)
    has_resend = bool(RESEND_API_KEY)
    has_gmail = len(GMAIL_APP_PASSWORD) >= 16
    configured = has_brevo or has_resend or has_gmail
    resend_sandbox = has_resend and _resend_sandbox() and not has_brevo
    provider = (
        "brevo"
        if has_brevo
        else ("resend" if has_resend else ("gmail" if has_gmail else "none"))
    )
    hint = None
    if not configured:
        hint = RENDER_SMTP_HELP if os.environ.get("RENDER") else APP_PASSWORD_HELP
    elif resend_sandbox and HOST_NOTIFY_EMAIL.lower() != SENDER_EMAIL.lower():
        hint = GUEST_EMAIL_HELP
    return jsonify(
        {
            "configured": configured,
            "sender": SENDER_EMAIL,
            "notifyEmail": HOST_NOTIFY_EMAIL,
            "provider": provider,
            "appPasswordLooksValid": has_gmail,
            "resendConfigured": has_resend,
            "brevoConfigured": has_brevo,
            "resendSandbox": resend_sandbox,
            "onRender": bool(os.environ.get("RENDER")),
            "hint": hint,
        }
    )


@app.route("/api/register-phone", methods=["POST"])
def register_phone():
    if not _email_ready():
        hint = RENDER_SMTP_HELP if os.environ.get("RENDER") else APP_PASSWORD_HELP
        return jsonify({"error": hint}), 503

    data = request.get_json(silent=True) or {}
    phone = _normalize_phone(str(data.get("phone") or ""))
    guest_email = str(data.get("email") or "").strip().lower()
    name = str(data.get("name") or "").strip()[:80]
    language = str(data.get("language") or "").strip()[:20]

    if not _phone_looks_valid(phone):
        return jsonify({"error": "Please enter a valid phone number."}), 400
    if not _email_looks_valid(guest_email):
        return jsonify({"error": "Please enter a valid email address."}), 400

    guest_line = f"{name} ({phone})" if name else phone
    subject = f"Singapore dinner registration: {guest_line}"
    body = f"""New Singapore dinner registration

Phone: {phone}
Email: {guest_email}
Name: {name or "(not provided)"}
Language: {language or "(not provided)"}

— {APP_NAME}
"""
    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;line-height:1.6;color:#102033">
<h2 style="margin:0 0 0.75rem">New Singapore dinner registration</h2>
<p><strong>Phone:</strong> {phone}</p>
<p><strong>Email:</strong> {guest_email}</p>
<p><strong>Name:</strong> {name or "(not provided)"}</p>
<p><strong>Language:</strong> {language or "(not provided)"}</p>
<p style="color:#5a6f82">— {APP_NAME}</p>
</body></html>"""

    try:
        provider = send_email(HOST_NOTIFY_EMAIL, subject, body, html_body)
        print(f"[rsvp] Sent via {provider} to {HOST_NOTIFY_EMAIL}: {guest_line}")
    except smtplib.SMTPAuthenticationError as exc:
        return jsonify({"error": _gmail_auth_error_message(exc)}), 500
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        print(f"[rsvp] Failed for {phone}: {exc}")
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "ok": True,
            "message": "Registered. Host has been notified.",
            "phone": phone,
            "email": guest_email,
        }
    )


@app.route("/api/send-dinner-rsvp", methods=["POST"])
def send_dinner_rsvp():
    if not _email_ready():
        hint = RENDER_SMTP_HELP if os.environ.get("RENDER") else APP_PASSWORD_HELP
        return jsonify({"error": hint}), 503

    data = request.get_json(silent=True) or {}
    phone = _normalize_phone(str(data.get("phone") or ""))
    guest_email = str(data.get("email") or "").strip().lower()
    name = str(data.get("name") or "").strip()[:80]
    language = str(data.get("language") or "").strip()[:20]
    visit_date = str(data.get("date") or "").strip()
    cuisines = data.get("cuisines") or []
    if not isinstance(cuisines, list):
        cuisines = []

    if not _phone_looks_valid(phone):
        return jsonify({"error": "Please enter a valid phone number."}), 400
    if not _email_looks_valid(guest_email):
        return jsonify({"error": "Please enter a valid email address."}), 400
    if not visit_date:
        return jsonify({"error": "Please select a dinner date."}), 400

    cuisine_lines = []
    html_cuisine_items = []
    for item in cuisines:
        if isinstance(item, dict):
            cname = str(item.get("name") or "").strip()
            desc = str(item.get("description") or "").strip()
        else:
            cname = str(item).strip()
            desc = ""
        if not cname:
            continue
        line = f"  • {cname}"
        if desc:
            line += f"\n    {desc}"
        cuisine_lines.append(line)
        html_desc = (
            f"<br><span style='color:#666;font-size:0.9em'>{desc}</span>" if desc else ""
        )
        html_cuisine_items.append(f"<li><strong>{cname}</strong>{html_desc}</li>")

    if not cuisine_lines:
        return jsonify({"error": "Please pick at least one cuisine."}), 400

    cuisines_text = "\n".join(cuisine_lines)
    html_cuisines = "".join(html_cuisine_items)
    guest_line = f"{name} ({phone})" if name else phone
    greeting = name or "there"

    host_subject = f"Singapore dinner YES: {guest_line} on {visit_date}"
    host_body = f"""New Singapore dinner RSVP

Phone: {phone}
Email: {guest_email}
Name: {name or "(not provided)"}
Language: {language or "(not provided)"}
Dinner date: {visit_date}

Preferred cuisine:
{cuisines_text}

— {APP_NAME}
"""
    host_html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;line-height:1.6;color:#102033">
<h2 style="margin:0 0 0.75rem">New Singapore dinner RSVP</h2>
<p><strong>Phone:</strong> {phone}</p>
<p><strong>Email:</strong> {guest_email}</p>
<p><strong>Name:</strong> {name or "(not provided)"}</p>
<p><strong>Language:</strong> {language or "(not provided)"}</p>
<p><strong>Dinner date:</strong> {visit_date}</p>
<p><strong>Preferred cuisine:</strong></p>
<ul>{html_cuisines}</ul>
<p style="color:#5a6f82">— {APP_NAME}</p>
</body></html>"""

    guest_subject = "You're booked for Singapore dinner!"
    guest_body = f"""Hello {greeting}!

Your Singapore dinner is successfully booked.

Date: {visit_date}
Phone on file: {phone}

Cuisine you picked:
{cuisines_text}

We can't wait to see you there.

— {SENDER_EMAIL}
"""
    guest_html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;line-height:1.6;color:#102033">
<h2 style="margin:0 0 0.75rem">You're booked for Singapore dinner!</h2>
<p>Hello {greeting}!</p>
<p>Your Singapore dinner is <strong>successfully booked</strong>.</p>
<p><strong>Date:</strong> {visit_date}</p>
<p><strong>Phone on file:</strong> {phone}</p>
<p><strong>Cuisine you picked:</strong></p>
<ul>{html_cuisines}</ul>
<p>We can't wait to see you there.</p>
<p style="color:#5a6f82">— {SENDER_EMAIL}</p>
</body></html>"""

    try:
        host_provider = send_email(HOST_NOTIFY_EMAIL, host_subject, host_body, host_html)
        print(f"[dinner] Host notify via {host_provider}: {guest_line} / {visit_date}")
        guest_provider = send_email(guest_email, guest_subject, guest_body, guest_html)
        print(f"[dinner] Guest invite via {guest_provider} to {guest_email}")
    except smtplib.SMTPAuthenticationError as exc:
        return jsonify({"error": _gmail_auth_error_message(exc)}), 500
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        print(f"[dinner] Failed for {phone} / {guest_email}: {exc}")
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"Dinner booked. Confirmation sent to {guest_email}.",
            "phone": phone,
            "email": guest_email,
            "date": visit_date,
        }
    )


@app.route("/api/send-verification", methods=["POST"])
def send_verification():
    if not _email_ready():
        return jsonify({"error": APP_PASSWORD_HELP}), 503

    subject = f"{APP_NAME} — email verification test"
    body = f"""This is a test email from your Dinner Invitation app.

If you received this, email is working for {SENDER_EMAIL}.
Host notify address: {HOST_NOTIFY_EMAIL}
"""

    try:
        send_email(HOST_NOTIFY_EMAIL, subject, body)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"Verification email sent to {HOST_NOTIFY_EMAIL}. Check inbox (and spam).",
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
