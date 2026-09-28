"""
memory.py — lightweight persistent memory for the email agent.

Uses SQLite (stdlib, no extra deps, single file on disk) so this runs fine
on a low-power laptop. Three jobs:

1. Dedup: never re-process/re-notify the same email twice.
2. Sender memory: remember how a sender's mail has been categorized before.
3. Corrections: store human overrides ("this was actually urgent") and use
   them to bias future classification for that sender / similar subjects.

One DB file per business, e.g. memory/acme_marketplace.db, memory/demo_school.db —
keeps businesses fully isolated from each other.
"""

import sqlite3
import os
import time
import json
from typing import Optional


class AgentMemory:
    def __init__(self, business_id: str, base_dir: str = "memory"):
        os.makedirs(base_dir, exist_ok=True)
        self.db_path = os.path.join(base_dir, f"{business_id}.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            email_id TEXT PRIMARY KEY,
            sender TEXT,
            subject TEXT,
            category TEXT,
            matched_by TEXT,       -- 'sender_rule' | 'keyword' | 'llm' | 'correction' | 'default'
            processed_at REAL,
            notified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sender_history (
            sender TEXT PRIMARY KEY,
            last_category TEXT,
            category_counts TEXT,   -- JSON dict {category_id: count}
            last_seen REAL
        );

        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id TEXT,
            sender TEXT,
            original_category TEXT,
            corrected_category TEXT,
            corrected_at REAL,
            note TEXT
        );
        """)
        self.conn.commit()

    # ---------- dedup ----------

    def already_processed(self, email_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM processed_emails WHERE email_id = ?", (email_id,)
        )
        return cur.fetchone() is not None

    def record_processed(self, email_id: str, sender: str, subject: str,
                          category: str, matched_by: str, notified: bool = False):
        self.conn.execute(
            """INSERT OR REPLACE INTO processed_emails
               (email_id, sender, subject, category, matched_by, processed_at, notified)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (email_id, sender, subject, category, matched_by, time.time(), int(notified)),
        )
        self._update_sender_history(sender, category)
        self.conn.commit()

    # ---------- sender memory ----------

    def _update_sender_history(self, sender: str, category: str):
        row = self.conn.execute(
            "SELECT category_counts FROM sender_history WHERE sender = ?", (sender,)
        ).fetchone()
        counts = json.loads(row["category_counts"]) if row else {}
        counts[category] = counts.get(category, 0) + 1
        self.conn.execute(
            """INSERT OR REPLACE INTO sender_history
               (sender, last_category, category_counts, last_seen)
               VALUES (?, ?, ?, ?)""",
            (sender, category, json.dumps(counts), time.time()),
        )

    def get_sender_bias(self, sender: str) -> Optional[str]:
        """
        Return the category this sender has most consistently been filed
        under, if there's a strong enough pattern (>=3 emails, >=70% one
        category). Used as a soft signal before falling back to keywords.
        """
        row = self.conn.execute(
            "SELECT category_counts FROM sender_history WHERE sender = ?", (sender,)
        ).fetchone()
        if not row:
            return None
        counts = json.loads(row["category_counts"])
        total = sum(counts.values())
        if total < 3:
            return None
        top_cat, top_count = max(counts.items(), key=lambda kv: kv[1])
        if top_count / total >= 0.7:
            return top_cat
        return None

    # ---------- corrections / feedback ----------

    def record_correction(self, email_id: str, sender: str, original_category: str,
                           corrected_category: str, note: str = ""):
        self.conn.execute(
            """INSERT INTO corrections
               (email_id, sender, original_category, corrected_category, corrected_at, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (email_id, sender, original_category, corrected_category, time.time(), note),
        )
        # A correction is a strong signal — immediately nudge sender history
        # by writing several "votes" for the corrected category.
        row = self.conn.execute(
            "SELECT category_counts FROM sender_history WHERE sender = ?", (sender,)
        ).fetchone()
        counts = json.loads(row["category_counts"]) if row else {}
        counts[corrected_category] = counts.get(corrected_category, 0) + 3
        self.conn.execute(
            """INSERT OR REPLACE INTO sender_history
               (sender, last_category, category_counts, last_seen)
               VALUES (?, ?, ?, ?)""",
            (sender, corrected_category, json.dumps(counts), time.time()),
        )
        # also fix the record if it was already processed
        self.conn.execute(
            "UPDATE processed_emails SET category = ?, matched_by = 'correction' WHERE email_id = ?",
            (corrected_category, email_id),
        )
        self.conn.commit()

    # ---------- stats / introspection ----------

    def category_totals(self) -> dict:
        cur = self.conn.execute(
            "SELECT category, COUNT(*) as n FROM processed_emails GROUP BY category ORDER BY n DESC"
        )
        return {row["category"]: row["n"] for row in cur.fetchall()}

    def recent(self, limit: int = 20):
        cur = self.conn.execute(
            "SELECT * FROM processed_emails ORDER BY processed_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        self.conn.close()
