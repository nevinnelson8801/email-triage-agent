"""
main.py — runs the agent for one business, end to end.

Usage:
    python main.py acme_marketplace
    python main.py demo_school

Each business's config.json controls which connector it uses via
"mailbox": {"connector": "mock" | "imap", ...}. Businesses on "mock"
read sample_data/; switching a business to "imap" makes
it read a real mailbox via connectors/imap_connector.py — nothing else in
main.py, classifier, memory, or actions needs to change either way.
"""

import sys
import json
import os

from connectors.mock_connector import MockConnector
from connectors.imap_connector import ImapConnector
from classifier.classifier import classify_email
from actions.actions import run_action
from memory import AgentMemory

CONNECTORS = {
    "mock": MockConnector,
    "imap": ImapConnector,
    # "gmail": GmailConnector,       # add if you need Gmail support
    # "outlook": OutlookConnector,
}


def load_business_config(business_id: str) -> dict:
    path = os.path.join("config", f"{business_id}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run(business_id: str, use_llm_fallback: bool = False):
    config = load_business_config(business_id)

    connector_name = config["mailbox"]["connector"]
    connector_cls = CONNECTORS[connector_name]

    conn_config = dict(config["mailbox"]["connection"])
    conn_config["business_id"] = business_id  # needed by ImapConnector to find its *_IMAP_* env vars

    if connector_name == "mock":
        conn_config["sample_file"] = f"sample_data/{business_id}_sample.json"

    connector = connector_cls(conn_config)

    memory = AgentMemory(business_id)

    llm_fallback = None
    if use_llm_fallback:
        from classifier.llm_fallback import classify_with_lm_studio
        llm_fallback = lambda email, categories: classify_with_lm_studio(email, categories)

    emails = connector.fetch_new_emails()
    print(f"\n=== {config['display_name']} — {len(emails)} emails fetched ===\n")

    results = []
    for email in emails:
        if memory.already_processed(email["id"]):
            continue

        classification = classify_email(email, config, memory, llm_fallback=llm_fallback)

        notified = classification.config.get("action") == "notify_immediately"
        run_action(business_id, email, classification, config)

        memory.record_processed(
            email_id=email["id"],
            sender=email["sender"],
            subject=email["subject"],
            category=classification.category_id,
            matched_by=classification.matched_by,
            notified=notified,
        )
        connector.apply_label(email["id"], classification.category_id)

        results.append((email, classification))
        print(f"  {email['id']:10s} -> {classification.category_id:20s} "
              f"({classification.matched_by})  [{email['subject'][:50]}]")

    print(f"\n--- Category totals (all-time, from memory) ---")
    for cat, count in memory.category_totals().items():
        print(f"  {cat}: {count}")

    memory.close()
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <business_id> [--llm]")
        sys.exit(1)

    business_id = sys.argv[1]
    use_llm = "--llm" in sys.argv
    run(business_id, use_llm_fallback=use_llm)
