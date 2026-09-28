"""
connectors/mock_connector.py — reads sample emails from a JSON file instead
of a real mailbox. This is what lets us build and test the whole agent
before connecting to a real mail system (Gmail, Outlook, IMAP, etc.).

Swap this out for connectors/imap_connector.py or connectors/gmail_connector.py
later — nothing else in the agent needs to change.
"""

import json
import os
from typing import List, Dict
from connectors.base import BaseConnector


class MockConnector(BaseConnector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.sample_file = config.get("sample_file")
        self._labels_applied = []

    def fetch_new_emails(self) -> List[Dict]:
        if not self.sample_file or not os.path.exists(self.sample_file):
            return []
        with open(self.sample_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def apply_label(self, email_id: str, label: str) -> None:
        self._labels_applied.append((email_id, label))
        # In a real connector this would call the provider's API.
        # print left out here to keep demo output focused on classification.
