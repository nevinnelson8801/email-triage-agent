"""
connectors/imap_connector.py — reads real email over IMAP, for mail servers
using standard IMAP4 (SSL/TLS on port 993 by default).

Also handles servers that use a self-signed certificate, via fingerprint
pinning rather than disabling certificate verification outright. Disabling
verification entirely would accept ANY certificate, including one from an
attacker — pinning the fingerprint means we only trust this one specific
certificate, which is the correct way to handle a legitimate self-signed cert.

--- Required environment variables (per business, using a prefix) ---
For business_id "demo_school", set:
    DEMO_SCHOOL_IMAP_HOST              e.g. "mail.example.com"
    DEMO_SCHOOL_IMAP_PORT              e.g. "993"
    DEMO_SCHOOL_IMAP_USER              e.g. "user@example.com"
    DEMO_SCHOOL_IMAP_PASSWORD          the mailbox password
    DEMO_SCHOOL_IMAP_CERT_FINGERPRINT  SHA-256 fingerprint of the server's
                                       certificate, colon-separated or plain
                                       hex — both formats accepted, e.g.
                                       "AA:BB:CC:...:DD:EE:FF"
                                       or "aabbcc...ddeeff"
                                       (placeholder values — use your own)

The connector reads {BUSINESS_ID}_IMAP_* automatically based on the
business_id passed into its config — no code changes needed to add a
second business on the same or a different IMAP server, just new env vars.

--- What this connector does ---
- Connects over implicit TLS (IMAP4_SSL), pinning the server certificate's
  SHA-256 fingerprint before completing the handshake.
- Logs in via IMAP LOGIN using the full email address as username.
- Fetches unseen messages from INBOX, parses sender/subject/body/date into
  the plain-dict Email format the rest of the agent expects (see base.py).
- apply_label() sets an IMAP flag — see the note in that method, since
  exact behavior depends on what the mail server supports.

--- What this connector deliberately does NOT do ---
- Does not mark messages as \\Seen automatically on fetch — dedup is left
  entirely to memory.py (AgentMemory.already_processed), so a message
  being "seen" by a human in a real mail client doesn't cause the agent to
  skip it, and vice versa. This mirrors the project's existing dedup design.
- Does not delete anything.
"""

import os
import ssl
import socket
import imaplib
import email
import email.message
import email.utils
import hashlib
import time
from datetime import datetime, timezone
from typing import List, Dict
from connectors.base import BaseConnector


def _env(business_id: str, key: str, default=None):
    return os.environ.get(f"{business_id.upper()}_{key}", default)


def _normalize_fingerprint(fp: str) -> str:
    """Accepts either 'AA:BB:CC:...' or 'aabbcc...' and returns lowercase hex, no separators."""
    return fp.replace(":", "").replace(" ", "").lower()


class _FingerprintPinnedIMAP4SSL(imaplib.IMAP4_SSL):
    """
    IMAP4_SSL subclass that verifies the server certificate's SHA-256
    fingerprint instead of relying on standard CA chain validation — needed
    because the server presents a self-signed certificate that will fail
    normal verification (DEPTH_ZERO_SELF_SIGNED_CERT), but should still be
    trusted because we've independently confirmed this exact fingerprint.
    """

    def __init__(self, host, port, expected_fingerprint: str, timeout: float = 15.0):
        self._expected_fingerprint = _normalize_fingerprint(expected_fingerprint)
        self._timeout = timeout
        super().__init__(host, port)

    def _create_socket(self, timeout=None):
        # Build a context that does NOT validate against the system CA store
        # (it would fail on a self-signed cert regardless of legitimacy) —
        # but we manually verify the fingerprint immediately after connecting,
        # which is the actual security check standing in for CA validation.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        raw_sock = socket.create_connection((self.host, self.port), timeout=self._timeout)
        ssl_sock = context.wrap_socket(raw_sock, server_hostname=self.host)

        der_cert = ssl_sock.getpeercert(binary_form=True)
        actual_fingerprint = hashlib.sha256(der_cert).hexdigest()

        if actual_fingerprint != self._expected_fingerprint:
            ssl_sock.close()
            raise ssl.SSLCertVerificationError(
                f"Certificate fingerprint mismatch for {self.host}: "
                f"expected {self._expected_fingerprint}, got {actual_fingerprint}. "
                f"Refusing connection — this may indicate a man-in-the-middle attack, "
                f"or the server's certificate was legitimately rotated (in which case, "
                f"confirm the new fingerprint out-of-band and update "
                f"*_IMAP_CERT_FINGERPRINT before retrying)."
            )

        return ssl_sock


class ImapConnector(BaseConnector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.business_id = config["business_id"]  # required — used to look up *_IMAP_* env vars
        self.folder = config.get("folder", "INBOX")

    def _connect(self) -> imaplib.IMAP4_SSL:
        business = self.business_id
        host = _env(business, "IMAP_HOST")
        port = int(_env(business, "IMAP_PORT", 993))
        user = _env(business, "IMAP_USER")
        password = _env(business, "IMAP_PASSWORD")
        fingerprint = _env(business, "IMAP_CERT_FINGERPRINT")

        missing = [name for name, val in [
            ("IMAP_HOST", host), ("IMAP_USER", user),
            ("IMAP_PASSWORD", password), ("IMAP_CERT_FINGERPRINT", fingerprint),
        ] if not val]
        if missing:
            raise RuntimeError(
                f"[{business}] Missing required env vars: "
                f"{', '.join(business.upper() + '_' + m for m in missing)}"
            )

        conn = _FingerprintPinnedIMAP4SSL(host, port, fingerprint)
        conn.login(user, password)
        return conn

    def fetch_new_emails(self) -> List[Dict]:
        conn = self._connect()
        emails = []
        try:
            conn.select(self.folder)
            # UNSEEN here just narrows what IMAP returns to us; actual dedup
            # authority remains memory.py, per this module's docstring.
            status, data = conn.search(None, "UNSEEN")
            if status != "OK":
                return []

            for num in data[0].split():
                status, msg_data = conn.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                message_id = msg.get("Message-ID", f"{self.business_id}-{num.decode()}")
                sender = email.utils.parseaddr(msg.get("From", ""))[1]
                subject = msg.get("Subject", "")

                body = _extract_plain_text_body(msg)

                date_header = msg.get("Date")
                received_at = time.time()
                if date_header:
                    try:
                        parsed_date = email.utils.parsedate_to_datetime(date_header)
                        if parsed_date.tzinfo is None:
                            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                        received_at = parsed_date.timestamp()
                    except (TypeError, ValueError):
                        pass  # fall back to time.time() above

                emails.append({
                    "id": message_id,
                    "sender": sender,
                    "subject": subject,
                    "body": body[:1000],
                    "received_at": received_at,
                })

            return emails
        finally:
            try:
                conn.close()
            except Exception:
                pass
            conn.logout()

    def apply_label(self, email_id: str, label: str) -> None:
        """
        IMAP doesn't have Gmail-style arbitrary labels natively — the two
        realistic options are:
          (a) set a custom IMAP flag, e.g. "Triage/urgent_support"
              (supported by many servers, but not universally)
          (b) copy/move the message into a folder named after the category

        This starts with (a), the less destructive option — it never moves
        or risks losing a message. Switch to folder-based filing later if
        you want that instead; the interface (this method's
        signature) won't need to change either way.
        """
        conn = self._connect()
        try:
            conn.select(self.folder)
            status, data = conn.search(None, f'(HEADER Message-ID "{email_id}")')
            if status == "OK" and data[0]:
                num = data[0].split()[0]
                conn.store(num, "+FLAGS", f"({label})")
        finally:
            try:
                conn.close()
            except Exception:
                pass
            conn.logout()


def _extract_plain_text_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    continue
        return ""
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            return msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            return str(msg.get_payload())
