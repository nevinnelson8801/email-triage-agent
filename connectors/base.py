"""
connectors/base.py — the interface every mail connector must implement.

This is the seam that keeps the agent independent of any one mail system.
Whatever is in use — Gmail, Outlook/Microsoft 365, plain IMAP,
a custom platform notification webhook — we write ONE class that implements
fetch_new_emails() and mark_as_read()/apply_label(), and the rest of the
agent (classifier, memory, actions) never has to change.

An Email is a plain dict for simplicity:
{
    "id": str,            # stable unique id (Message-ID header or provider id)
    "sender": str,        # email address
    "subject": str,
    "body": str,          # plain text, first ~1000 chars is enough
    "received_at": float  # unix timestamp
}
"""

from abc import ABC, abstractmethod
from typing import List, Dict


class BaseConnector(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def fetch_new_emails(self) -> List[Dict]:
        """Return a list of new/unseen emails as dicts (see module docstring)."""
        raise NotImplementedError

    @abstractmethod
    def apply_label(self, email_id: str, label: str) -> None:
        """Apply a folder/label/tag to an email in the source system."""
        raise NotImplementedError

    def notify(self, message: str) -> None:
        """
        Optional override. Default just prints — real implementations can
        push to Slack, send a digest email, etc. Kept on the connector for
        now since notification channel is often tied to the same account.
        """
        print(f"[NOTIFY] {message}")
