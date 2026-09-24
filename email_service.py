"""
email_service.py — Kutuma OTP kwa HTTPS (Brevo API) badala ya SMTP.

Render inazuia SMTP (port 25/465/587) kwenye mpango wa bure, kwa hiyo
smtplib inaning'inia. HTTPS inaruhusiwa, na hapa kuna timeout ya sekunde 10.

Environment variables zinazohitajika (Render > Environment):
    BREVO_API_KEY     -> API key kutoka Brevo (SMTP & API > API Keys)
    MAIL_FROM_EMAIL   -> email ya sender uliyoithibitisha kwenye Brevo
    MAIL_FROM_NAME    -> (hiari) jina linaloonekana, default "Kijiji Tanzania"
"""
import os
import requests

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SECONDS = 10

_SUBJECTS = {
    "register": "Code yako ya kuthibitisha akaunti",
    "reset": "Code yako ya kubadilisha nenosiri",
}


def send_otp_email(email, otp, purpose="register"):
    """Tuma OTP. Rudisha True kama imetumwa, False kama imeshindwa.
    Haitupi exception na haisubiri zaidi ya TIMEOUT_SECONDS."""
    api_key = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("MAIL_FROM_EMAIL")
    sender_name = os.environ.get("MAIL_FROM_NAME", "Kijiji Tanzania")

    if not api_key or not sender_email:
        print("[MAIL] BREVO_API_KEY au MAIL_FROM_EMAIL haijawekwa!")
        return False

    subject = _SUBJECTS.get(purpose, "Code yako ya uthibitisho")
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:420px'>"
        f"<h2>{subject}</h2>"
        f"<p>Tumia code hii:</p>"
        f"<p style='font-size:32px;font-weight:bold;letter-spacing:6px'>{otp}</p>"
        f"<p>Inaexpire baada ya dakika 5. Usimpe mtu yeyote code hii.</p>"
        f"</div>"
    )

    try:
        r = requests.post(
            BREVO_URL,
            headers={
                "api-key": api_key,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json={
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": email}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=TIMEOUT_SECONDS,
        )
        if r.status_code in (200, 201):
            return True
        print(f"[MAIL] Brevo error {r.status_code}: {r.text[:300]}")
        return False
    except requests.RequestException as e:
        print("[MAIL] request failed:", e)
        return False
