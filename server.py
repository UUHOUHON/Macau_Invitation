"""
Macau invitation server — sends email via Gmail SMTP.
Set GMAIL_APP_PASSWORD in .env (16-character Google App Password, not login password).
"""

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "houhonuhh@gmail.com").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")

app = Flask(__name__, static_folder=".")

APP_PASSWORD_HELP = (
    "Email is not configured. Create a 16-character Google App Password at "
    "https://myaccount.google.com/apppasswords then set GMAIL_APP_PASSWORD "
    "(local: .env file | Render: Environment tab) and redeploy."
)


def _gmail_auth_error_message(exc: smtplib.SMTPAuthenticationError) -> str:
    detail = (exc.smtp_error or b"").decode(errors="ignore").lower()
    if "application-specific password" in detail or exc.smtp_code == 534:
        if len(GMAIL_APP_PASSWORD) < 16:
            return APP_PASSWORD_HELP
        return (
            "Gmail rejected the App Password. Create a new one at "
            "https://myaccount.google.com/apppasswords and update GMAIL_APP_PASSWORD in .env."
        )
    return "Gmail login failed. Check SENDER_EMAIL and GMAIL_APP_PASSWORD in .env."


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

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [recipient], raw)
            return
    except smtplib.SMTPAuthenticationError as exc:
        last_auth_error = exc

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls(context=context)
            server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [recipient], raw)
            return
    except smtplib.SMTPAuthenticationError as exc:
        last_auth_error = exc

    if last_auth_error:
        raise last_auth_error
    raise RuntimeError("Could not connect to Gmail SMTP.")


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/email-status", methods=["GET"])
def email_status():
    if not GMAIL_APP_PASSWORD:
        return jsonify({"configured": False, "hint": APP_PASSWORD_HELP})
    return jsonify(
        {
            "configured": True,
            "sender": SENDER_EMAIL,
            "appPasswordLooksValid": len(GMAIL_APP_PASSWORD) >= 16,
        }
    )


@app.route("/api/send-invitation", methods=["POST"])
def send_invitation():
    if not GMAIL_APP_PASSWORD:
        return jsonify({"error": APP_PASSWORD_HELP}), 503

    if len(GMAIL_APP_PASSWORD) < 16:
        return jsonify({"error": APP_PASSWORD_HELP}), 503

    data = request.get_json(silent=True) or {}
    recipient = (data.get("email") or "").strip()
    visit_date = (data.get("date") or "").strip()
    activities = data.get("activities") or []
    if not isinstance(activities, list):
        activities = []
    activities = [str(a).strip() for a in activities if str(a).strip()]
    activities_text = "\n".join(f"  • {a}" for a in activities) if activities else "  • (none selected)"

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
    html_activities = "".join(f"<li>{a}</li>" for a in activities) or "<li>(none selected)</li>"
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
        send_via_gmail(recipient, subject, body, html_body)
        print(f"[email] Invitation sent to {recipient} (date {visit_date})")
    except smtplib.SMTPAuthenticationError as exc:
        return jsonify({"error": _gmail_auth_error_message(exc)}), 500
    except Exception as exc:
        print(f"[email] Failed to {recipient}: {exc}")
        return jsonify({"error": f"Failed to send email: {exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"Invitation sent to {recipient}. Check inbox and spam.",
            "recipient": recipient,
        }
    )


@app.route("/api/send-verification", methods=["POST"])
def send_verification():
    """Send a test email to the configured Gmail inbox to verify SMTP works."""
    if not GMAIL_APP_PASSWORD:
        return jsonify({"error": APP_PASSWORD_HELP}), 503

    if len(GMAIL_APP_PASSWORD) < 16:
        return jsonify({"error": APP_PASSWORD_HELP}), 503

    subject = "Macau Invitation — Gmail verification test"
    body = f"""This is a test email from your Macau Invitation app.

If you received this message, Gmail SMTP is working correctly for {SENDER_EMAIL}.

You can share your invitation link with guests — they will receive invitations from this address after picking a date.
"""

    try:
        send_via_gmail(SENDER_EMAIL, subject, body)
    except smtplib.SMTPAuthenticationError as exc:
        return jsonify({"error": _gmail_auth_error_message(exc)}), 500
    except Exception as exc:
        return jsonify({"error": f"Failed to send verification: {exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"Verification email sent to {SENDER_EMAIL}. Check your inbox (and spam).",
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
