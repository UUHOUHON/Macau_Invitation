"""
Macau invitation server — sends email via Gmail SMTP (local) or Resend API (Render).
"""

import json
import os
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
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM = os.environ.get(
    "RESEND_FROM", "Macau Invitation <onboarding@resend.dev>"
).strip()

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
    msg["From"] = formataddr(("Macau Invitation", SENDER_EMAIL))
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
                "Go to resend.com/domains to add one, or test with your Gmail address first."
            )
        return f"Resend: {msg}"
    except json.JSONDecodeError:
        if "1010" in detail:
            return "Resend connection blocked. Redeploy after the latest update (User-Agent fix)."
        return f"Resend error: {detail[:200]}"


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
            "User-Agent": "macau-invitation-web/1.0 (Render)",
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
    """Send email. Returns provider name used: 'resend' or 'gmail'."""
    on_render = bool(os.environ.get("RENDER"))

    if RESEND_API_KEY:
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


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/email-status", methods=["GET"])
def email_status():
    has_resend = bool(RESEND_API_KEY)
    has_gmail = len(GMAIL_APP_PASSWORD) >= 16
    configured = has_resend or has_gmail
    return jsonify(
        {
            "configured": configured,
            "sender": SENDER_EMAIL,
            "provider": "resend" if has_resend else ("gmail" if has_gmail else "none"),
            "appPasswordLooksValid": has_gmail,
            "resendConfigured": has_resend,
            "onRender": bool(os.environ.get("RENDER")),
            "hint": None
            if configured
            else (RENDER_SMTP_HELP if os.environ.get("RENDER") else APP_PASSWORD_HELP),
        }
    )


@app.route("/api/send-invitation", methods=["POST"])
def send_invitation():
    if not RESEND_API_KEY and (not GMAIL_APP_PASSWORD or len(GMAIL_APP_PASSWORD) < 16):
        hint = RENDER_SMTP_HELP if os.environ.get("RENDER") else APP_PASSWORD_HELP
        return jsonify({"error": hint}), 503

    data = request.get_json(silent=True) or {}
    recipient = (data.get("email") or "").strip()
    visit_date = (data.get("date") or "").strip()
    activities = data.get("activities") or []
    if not isinstance(activities, list):
        activities = []

    activity_lines = []
    html_activity_items = []
    for item in activities:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            desc = str(item.get("description") or "").strip()
        else:
            name = str(item).strip()
            desc = ""
        if not name:
            continue
        line = f"  • {name}"
        if desc:
            line += f"\n    {desc}"
        activity_lines.append(line)
        html_desc = f"<br><span style='color:#666;font-size:0.9em'>{desc}</span>" if desc else ""
        html_activity_items.append(f"<li><strong>{name}</strong>{html_desc}</li>")

    activities_text = "\n".join(activity_lines) if activity_lines else "  • (none selected)"
    html_activities = "".join(html_activity_items) or "<li>(none selected)</li>"

    if not recipient or "@" not in recipient:
        return jsonify({"error": "Invalid email address."}), 400
    if not visit_date:
        return jsonify({"error": "Please select a date."}), 400

    subject = "You're invited to Macau!"
    body = f"""Hello!

You accepted an invitation to Macau!

Your chosen date: {visit_date}

Activities you picked:
{activities_text}

We can't wait to see you there.

— {SENDER_EMAIL}
"""
    html_activities = "".join(html_activity_items) or "<li>(none selected)</li>"
    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;line-height:1.6;color:#2a1f1f">
<p>Hello!</p>
<p>You accepted an invitation to <strong>Macau</strong>!</p>
<p>Your chosen date: <strong>{visit_date}</strong></p>
<p>Activities you picked:</p>
<ul>{html_activities}</ul>
<p>We can't wait to see you there.</p>
<p style="color:#666">— {SENDER_EMAIL}</p>
</body></html>"""

    try:
        provider = send_email(recipient, subject, body, html_body)
        print(f"[email] Sent via {provider} to {recipient} (date {visit_date})")
    except smtplib.SMTPAuthenticationError as exc:
        return jsonify({"error": _gmail_auth_error_message(exc)}), 500
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        print(f"[email] Failed to {recipient}: {exc}")
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"Invitation sent to {recipient}. Check inbox and spam.",
            "recipient": recipient,
        }
    )


@app.route("/api/send-verification", methods=["POST"])
def send_verification():
    if not RESEND_API_KEY and (not GMAIL_APP_PASSWORD or len(GMAIL_APP_PASSWORD) < 16):
        return jsonify({"error": APP_PASSWORD_HELP}), 503

    subject = "Macau Invitation — email verification test"
    body = f"""This is a test email from your Macau Invitation app.

If you received this, email is working for {SENDER_EMAIL}.
"""

    try:
        send_email(SENDER_EMAIL, subject, body)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"Verification email sent to {SENDER_EMAIL}. Check inbox (and spam).",
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
