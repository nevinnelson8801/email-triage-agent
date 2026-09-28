"""
actions/reply_drafter.py — drafts a reply to an email using business
context, and sends the draft to you via WhatsApp (CallMeBot) for review.

THIS NEVER SENDS ANYTHING TO THE ORIGINAL SENDER. It only:
  1. Reads the business context file (config/<business_id>_context.md)
  2. Asks Gemini to draft a reply based on that context + the email
  3. Sends the draft TO YOU via WhatsApp, clearly labeled as a draft
You copy/edit/send it yourself from your own mail client.

Why Gemini: free tier, no credit card, generous enough quota that this
project's email volume will never come close to hitting it. Needs
GEMINI_API_KEY set as an env var / GitHub Secret — get one at
https://aistudio.google.com/apikey (no billing required for the free tier).

Worth knowing: on Gemini's FREE tier specifically, Google's terms allow
using API inputs/outputs to improve their products — meaning email
content and business context sent here could be used as training data
unless billing is enabled. If that's a concern given this handles real
customer emails, switching to a paid Gemini tier (or back to Claude)
is a one-function change — see draft_reply() below.

Why the prompt is strict about "don't invent specifics": a wrong price,
wrong promise, or wrong commitment going out under the business's name is
worse than no draft at all. The model is explicitly told to mark anything
not covered by the context file as [NEEDS INPUT: ...] rather than guess.

If GEMINI_API_KEY isn't set, this runs in dry-run mode (prints instead
of calling the API), same pattern as the other actions/ modules.
"""

import os
import json
import urllib.request
import urllib.error

GEMINI_MODEL = "gemini-2.5-flash"  # good quality/free-quota balance; swap to
                                    # "gemini-2.5-flash-lite" for higher daily
                                    # throughput if ever needed
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def _load_business_context(business_id: str, config_dir: str = "config") -> str:
    path = os.path.join(config_dir, f"{business_id}_context.md")
    if not os.path.exists(path):
        return ""  # draft_reply() handles the empty case explicitly
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_prompt(email: dict, classification, business_context: str) -> str:
    return f"""You are drafting an email reply on behalf of a business. Use ONLY the
business context below — do not invent pricing, dates, policies, or
commitments that aren't stated in it. If the reply would need a specific
fact not covered by the context, write "[NEEDS INPUT: what's missing]"
in that spot instead of guessing.

Style requirements — follow these strictly:
- Always address the recipient directly and personally (use their name if
  it can reasonably be inferred from the sender's email/subject; otherwise
  a warm, generic greeting like "Hi there,").
- Always write in a polite, warm, professional tone — never curt or cold.
- Do NOT mention that this reply is AI-generated, automated, a draft, or
  produced by any tool. It should read exactly like a normal reply
  personally written by someone at the business.
- End with a natural, appropriate sign-off (no signature name needed —
  that gets added by the person sending it).

--- BUSINESS CONTEXT ---
{business_context if business_context else "(no context file found — flag everything specific as [NEEDS INPUT])"}
--- END BUSINESS CONTEXT ---

--- INCOMING EMAIL ---
From: {email.get('sender', '')}
Subject: {email.get('subject', '')}
Category: {classification.config.get('label', classification.category_id)}
Body:
{email.get('body', '')[:1000]}
--- END INCOMING EMAIL ---

Draft a reply email. Output ONLY the reply body text (no subject line,
no "Dear X," meta-commentary, no explanation of your choices) — just the
message as it should be sent."""


def draft_reply(email: dict, classification, business_id: str,
                 config_dir: str = "config", timeout: float = 20.0) -> str:
    business_context = _load_business_context(business_id, config_dir)
    prompt = _build_prompt(email, classification, business_context)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        dry_run_text = "[DRY RUN — GEMINI_API_KEY not set, no draft generated]"
        print(f"[REPLY DRAFTER - DRY RUN]\n{dry_run_text}\n")
        return dry_run_text

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 600, "temperature": 0.4},
    }
    url = f"{GEMINI_API_URL}?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            candidates = result.get("candidates", [])
            if not candidates:
                return "[REPLY DRAFTER ERROR — no candidates returned, possibly blocked by safety filters]"
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "\n".join(p.get("text", "") for p in parts).strip()
            return text or "[REPLY DRAFTER ERROR — empty response]"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[REPLY DRAFTER ERROR] {e.code}: {error_body}")
        return f"[REPLY DRAFTER ERROR — draft failed, check logs: {e.code}]"
    except Exception as e:
        print(f"[REPLY DRAFTER ERROR] {e}")
        return f"[REPLY DRAFTER ERROR — draft failed: {e}]"


def send_draft_via_whatsapp(business_id: str, email: dict, classification, draft_text: str) -> dict:
    """
    Sends the drafted reply to you via CallMeBot, clearly labeled as a
    DRAFT that needs review — never sent to the original sender directly.
    Reuses the same CALLMEBOT_PHONE / CALLMEBOT_APIKEY env vars as alerts.
    """
    from actions.callmebot import _credentials_configured
    import urllib.parse

    message_body = (
        f"[{business_id.upper()}] DRAFT REPLY — review before sending\n"
        f"To: {email.get('sender')}\n"
        f"Re: {email.get('subject')}\n"
        f"Category: {classification.config.get('label', classification.category_id)}\n\n"
        f"{draft_text}"
    )

    if not _credentials_configured():
        print(f"[REPLY DRAFTER/WHATSAPP - DRY RUN, no CallMeBot credentials set]\n{message_body}\n")
        return {"status": "dry_run", "body": message_body}

    phone = os.environ["CALLMEBOT_PHONE"]
    apikey = os.environ["CALLMEBOT_APIKEY"]

    # CallMeBot messages have a practical length limit over GET — trim
    # generously but keep the draft readable; full email thread is still
    # in the mailbox itself if more context is needed.
    params = urllib.parse.urlencode({
        "phone": phone,
        "text": message_body[:1500],
        "apikey": apikey,
    })
    url = f"https://api.callmebot.com/whatsapp.php?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            result_text = resp.read().decode("utf-8")
            return {"status": "sent", "response": result_text, "body": message_body}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[REPLY DRAFTER/WHATSAPP ERROR] {e.code}: {error_body}")
        return {"status": "error", "error": error_body, "body": message_body}
    except Exception as e:
        print(f"[REPLY DRAFTER/WHATSAPP ERROR] {e}")
        return {"status": "error", "error": str(e), "body": message_body}


def draft_and_send(business_id: str, email: dict, classification, config_dir: str = "config") -> dict:
    """Convenience wrapper: draft the reply, then send it to you via WhatsApp."""
    draft_text = draft_reply(email, classification, business_id, config_dir=config_dir)
    return send_draft_via_whatsapp(business_id, email, classification, draft_text)
