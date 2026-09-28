"""
actions/callmebot.py — sends WhatsApp alerts via CallMeBot, a free,
zero-signup WhatsApp API built for exactly this use case: one person
getting automated messages on their own WhatsApp number.

One-time setup (the person receiving alerts does this, once):
1. Save +34 623 78 95 80 as a contact on the phone that should get alerts.
   (CallMeBot's bot number rotates occasionally — always confirm the
   current one at https://www.callmebot.com/blog/free-api-whatsapp-messages/
   before assuming this is still correct.)
2. From that WhatsApp number, send this message to that contact:
       "I allow callmebot to send me messages"
3. CallMeBot replies with a personal apikey.

Then set two environment variables:
    CALLMEBOT_PHONE   your number WITH the + and country code,
                       e.g. "+15551234567"
    CALLMEBOT_APIKEY  the key from step 3

No account, no business verification, no dashboard. Free.

Limitations worth knowing:
- Unofficial/third-party — not run by WhatsApp/Meta, so it can go down or
  change without notice (including the bot's phone number itself — verify
  it's current if activation ever stops working). Fine for personal
  alerts, not for anything business-critical or high-volume.
- Rate limited (roughly one message per few seconds; fine for this use case).
- Only sends TO the number that opted in — can't message arbitrary numbers.

If credentials aren't set, this runs in dry-run mode like the Twilio path.
"""

import os
import urllib.request
import urllib.parse
import urllib.error


def _credentials_configured() -> bool:
    return bool(os.environ.get("CALLMEBOT_PHONE") and os.environ.get("CALLMEBOT_APIKEY"))


def send_callmebot_alert(business_id: str, email: dict, classification) -> dict:
    message_body = (
        f"[{business_id.upper()}] {classification.config['label']}\n"
        f"From: {email.get('sender')}\n"
        f"Subject: {email.get('subject')}\n"
        f"{email.get('body', '')[:180]}"
    )

    if not _credentials_configured():
        print(f"[WHATSAPP/CallMeBot - DRY RUN, no credentials set]\n{message_body}\n")
        return {"status": "dry_run", "body": message_body}

    phone = os.environ["CALLMEBOT_PHONE"]
    apikey = os.environ["CALLMEBOT_APIKEY"]

    params = urllib.parse.urlencode({
        "phone": phone,
        "text": message_body,
        "apikey": apikey,
    })
    url = f"https://api.callmebot.com/whatsapp.php?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            result_text = resp.read().decode("utf-8")
            return {"status": "sent", "response": result_text, "body": message_body}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[WHATSAPP/CallMeBot ERROR] {e.code}: {error_body}")
        return {"status": "error", "error": error_body, "body": message_body}
    except Exception as e:
        print(f"[WHATSAPP/CallMeBot ERROR] {e}")
        return {"status": "error", "error": str(e), "body": message_body}
