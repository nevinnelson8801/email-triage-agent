"""
actions/meta_whatsapp.py — sends WhatsApp alerts via Meta's official
WhatsApp Cloud API. Free for up to 1,000 conversations/month, run directly
by Meta rather than a third party.

--- One-time setup ---
1. Go to https://developers.facebook.com and create a developer account
   (uses a normal Facebook account).
2. Create a new App -> type "Business" -> add the "WhatsApp" product.
3. Meta gives you a TEST phone number and a temporary access token for
   free, immediately, no business verification needed to start testing.
   (Business verification is only required later, to remove the test
   number's limits and message non-test recipients.)
4. In the WhatsApp > API Setup page you'll find:
     - Phone number ID        -> META_PHONE_NUMBER_ID
     - Temporary access token -> META_WHATSAPP_TOKEN (valid 24h; generate
       a permanent one later via a System User once verified)
5. Add the recipient's WhatsApp number as a "test recipient" in that same
   page while testing (Meta requires this before verification is done).
6. Set three environment variables (see below).

--- The 24-hour window caveat (important) ---
Meta only allows free-form messages within 24 hours of the recipient last
messaging the business number. For an alert bot messaging the recipient unprompted,
that means one of:
  (a) The recipient sends any WhatsApp message to the business number once a day to
      keep the window open (simplest for personal use), or
  (b) Alerts use a pre-approved message template, which can be sent
      anytime regardless of the window (needed for real "fire whenever
      something urgent happens" behavior).

This module tries a free-form message first. If Meta rejects it for being
outside the window (error code 131047 / 470), it automatically retries
using a template, if META_WHATSAPP_TEMPLATE is set. Otherwise it just
reports the error so you know a template needs to be created.

Environment variables:
    META_WHATSAPP_TOKEN      access token (temporary or permanent)
    META_PHONE_NUMBER_ID     the business number's ID from API Setup
    META_TO_NUMBER           recipient's number, digits only with country
                             code, e.g. "15551234567" (no + or spaces)
    META_WHATSAPP_TEMPLATE   optional: name of an approved template to use
                             as a fallback when outside the 24h window
"""

import os
import json
import urllib.request
import urllib.error

GRAPH_API_VERSION = "v20.0"


def _credentials_configured() -> bool:
    return all([
        os.environ.get("META_WHATSAPP_TOKEN"),
        os.environ.get("META_PHONE_NUMBER_ID"),
        os.environ.get("META_TO_NUMBER"),
    ])


def _post(payload: dict, token: str, phone_number_id: str) -> dict:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_meta_whatsapp_alert(business_id: str, email: dict, classification) -> dict:
    message_body = (
        f"[{business_id.upper()}] {classification.config['label']}\n"
        f"From: {email.get('sender')}\n"
        f"Subject: {email.get('subject')}\n"
        f"{email.get('body', '')[:180]}"
    )

    if not _credentials_configured():
        print(f"[WHATSAPP/Meta - DRY RUN, no credentials set]\n{message_body}\n")
        return {"status": "dry_run", "body": message_body}

    token = os.environ["META_WHATSAPP_TOKEN"]
    phone_number_id = os.environ["META_PHONE_NUMBER_ID"]
    to_number = os.environ["META_TO_NUMBER"]
    template_name = os.environ.get("META_WHATSAPP_TEMPLATE")

    free_form_payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_body},
    }

    try:
        result = _post(free_form_payload, token, phone_number_id)
        return {"status": "sent", "response": result, "body": message_body}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        outside_window = "131047" in error_body or "470" in error_body

        if outside_window and template_name:
            # retry using the approved template, which works outside the window
            template_payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": "en_US"},
                    "components": [{
                        "type": "body",
                        "parameters": [{"type": "text", "text": message_body[:1024]}],
                    }],
                },
            }
            try:
                result = _post(template_payload, token, phone_number_id)
                return {"status": "sent_via_template", "response": result, "body": message_body}
            except urllib.error.HTTPError as e2:
                error_body2 = e2.read().decode("utf-8")
                print(f"[WHATSAPP/Meta ERROR - template also failed] {e2.code}: {error_body2}")
                return {"status": "error", "error": error_body2, "body": message_body}

        if outside_window:
            print(
                "[WHATSAPP/Meta ERROR] Outside 24h messaging window and no "
                "META_WHATSAPP_TEMPLATE configured. Either have the recipient "
                "message the business number to reopen the window, or set up "
                "an approved template for proactive alerts."
            )
        else:
            print(f"[WHATSAPP/Meta ERROR] {e.code}: {error_body}")
        return {"status": "error", "error": error_body, "body": message_body}

    except Exception as e:
        print(f"[WHATSAPP/Meta ERROR] {e}")
        return {"status": "error", "error": str(e), "body": message_body}
