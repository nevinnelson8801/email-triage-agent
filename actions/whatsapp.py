"""
actions/whatsapp.py — sends "important" email alerts to WhatsApp via Twilio's
WhatsApp API.

Why Twilio: it's the fastest path to a working WhatsApp integration.
Meta's own Cloud API is free but requires business verification that can
take days. Twilio's WhatsApp Sandbox works in minutes for testing, and the
same code path works once you upgrade to a real Twilio WhatsApp sender.

Setup (one-time):
1. Create a free Twilio account: https://www.twilio.com/try-twilio
2. Go to Messaging > Try it out > Send a WhatsApp message — this gives you
   a sandbox number and a join code.
3. From the WhatsApp number that should get alerts, send the join code to the
   Twilio sandbox number (one-time, links that WhatsApp to the sandbox).
4. Set four environment variables (see below) — never hardcode these.

Environment variables required:
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_WHATSAPP_FROM   e.g. "whatsapp:+14155238886" (Twilio sandbox number)
    TWILIO_WHATSAPP_TO     e.g. "whatsapp:+15551234567" (the recipient's WhatsApp number)

If these aren't set, send_whatsapp_alert() runs in DRY RUN mode: it prints
exactly what would have been sent instead of failing. This lets us test the
whole pipeline before Twilio is actually configured.
"""

import os
import json
import urllib.request
import urllib.parse
import urllib.error

TWILIO_API_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def _credentials_configured() -> bool:
    return all([
        os.environ.get("TWILIO_ACCOUNT_SID"),
        os.environ.get("TWILIO_AUTH_TOKEN"),
        os.environ.get("TWILIO_WHATSAPP_FROM"),
        os.environ.get("TWILIO_WHATSAPP_TO"),
    ])


def send_whatsapp_alert(business_id: str, email: dict, classification) -> dict:
    """
    Sends one WhatsApp message summarizing an important email.
    Returns a dict describing what happened — useful for logging/testing.
    """
    message_body = (
        f"[{business_id.upper()}] {classification.config['label']}\n"
        f"From: {email.get('sender')}\n"
        f"Subject: {email.get('subject')}\n"
        f"{email.get('body', '')[:180]}"
    )

    if not _credentials_configured():
        print(f"[WHATSAPP - DRY RUN, no Twilio credentials set]\n{message_body}\n")
        return {"status": "dry_run", "body": message_body}

    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    from_number = os.environ["TWILIO_WHATSAPP_FROM"]
    to_number = os.environ["TWILIO_WHATSAPP_TO"]

    url = TWILIO_API_URL.format(sid=sid)
    data = urllib.parse.urlencode({
        "From": from_number,
        "To": to_number,
        "Body": message_body,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    credentials = f"{sid}:{token}".encode("utf-8")
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(credentials).decode("utf-8"))
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return {"status": "sent", "sid": result.get("sid"), "body": message_body}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[WHATSAPP ERROR] {e.code}: {error_body}")
        return {"status": "error", "error": error_body, "body": message_body}
    except Exception as e:
        print(f"[WHATSAPP ERROR] {e}")
        return {"status": "error", "error": str(e), "body": message_body}
