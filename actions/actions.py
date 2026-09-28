"""
actions/actions.py — what happens after an email is classified.

notify() -> prints/logs (swap for Slack/email digest once known)

write_to_obsidian() is still defined below but NOT called by run_action()
right now — Obsidian export is disabled. Re-enable by uncommenting the
call at the bottom of run_action() if/when it's wanted again (e.g. once
there's a real vault path worth pointing vault_dir at).

apply_label() on the connector handles the "move/tag in the mail system"
side — that's provider-specific and lives in the connector, not here.
"""

import os
import datetime
from actions.whatsapp import send_whatsapp_alert
from actions.callmebot import send_callmebot_alert
from actions.meta_whatsapp import send_meta_whatsapp_alert
from actions.reply_drafter import draft_and_send


def notify(business_id: str, email: dict, classification) -> None:
    print(f"[{business_id}] NOTIFY [{classification.category_id}] "
          f"{email.get('subject')!r} from {email.get('sender')}")


def write_to_obsidian(business_id: str, email: dict, classification,
                       vault_dir: str = "obsidian_export") -> str:
    """
    Appends one markdown entry to a per-business, per-day note.
    e.g. obsidian_export/acme_marketplace/2026-08-23.md
    Point vault_dir at your real Obsidian vault path to have these show
    up directly in Obsidian.
    """
    folder = os.path.join(vault_dir, business_id)
    os.makedirs(folder, exist_ok=True)

    day = datetime.datetime.fromtimestamp(email.get("received_at", 0)).strftime("%Y-%m-%d") \
        if email.get("received_at") else datetime.date.today().isoformat()
    filepath = os.path.join(folder, f"{day}.md")

    email_id = email.get("id", "")
    marker = f"<!-- id:{email_id} -->"

    # guard against duplicate notes if memory was reset/wiped independently
    # of the obsidian export (e.g. during testing, or a DB migration)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            if marker in f.read():
                return filepath

    entry = (
        f"{marker}\n"
        f"## {classification.config['label']}\n"
        f"- **From:** {email.get('sender')}\n"
        f"- **Subject:** {email.get('subject')}\n"
        f"- **Category:** `{classification.category_id}` (matched by {classification.matched_by})\n"
        f"- **Preview:** {email.get('body', '')[:200]}\n\n---\n\n"
    )

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(entry)

    return filepath


def run_action(business_id: str, email: dict, classification, business_config: dict,
               vault_dir: str = "obsidian_export") -> None:
    action_id = classification.config.get("action")
    action_def = business_config.get("actions", {}).get(action_id, {})
    action_type = action_def.get("type")

    if action_type == "whatsapp":
        send_whatsapp_alert(business_id, email, classification)
    elif action_type == "whatsapp_free":
        send_callmebot_alert(business_id, email, classification)
    elif action_type == "whatsapp_meta":
        send_meta_whatsapp_alert(business_id, email, classification)
    elif action_type == "slack_or_email_digest":
        notify(business_id, email, classification)
    # Obsidian export disabled — see module docstring.
    # write_to_obsidian(business_id, email, classification, vault_dir)

    # Reply drafting is opt-in per category via "draft_reply": true in the
    # business config — off by default everywhere. Runs independently of
    # which action_type fired above, so a category can both alert AND
    # get a drafted reply. Never sends anything to the original sender —
    # only sends the draft to you via WhatsApp for review. See
    # actions/reply_drafter.py for details.
    if classification.config.get("draft_reply"):
        draft_and_send(business_id, email, classification)
