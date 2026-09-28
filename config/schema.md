# Business profile config schema

Each business gets one JSON file in /config, e.g. `acme_marketplace.json`,
`demo_school.json`. This is the ONLY thing that changes between businesses —
the engine code never branches on business name.

```json
{
  "business_id": "acme_marketplace",
  "display_name": "Acme Marketplace",
  "mailbox": {
    "connector": "mock",          // "mock" | "imap" | "gmail" | "outlook" (pick the one your mail system uses)
    "connection": {}                // provider-specific creds/settings, filled in later
  },
  "categories": [
    {
      "id": "urgent",
      "label": "Urgent / Support",
      "description": "Safety reports, payment disputes, angry customers, anything needing same-day response",
      "priority": 1,                 // 1 = highest
      "keywords": ["urgent", "complaint", "scam", "fraud", "not working", "refund"],
      "sender_rules": [],            // e.g. specific domains/addresses always land here
      "action": "notify_immediately"
    },
    {
      "id": "invoices",
      "label": "Invoices / Billing",
      "description": "Incoming vendor invoices, payment receipts, billing notices",
      "priority": 2,
      "keywords": ["invoice", "receipt", "payment due", "billing"],
      "sender_rules": ["billing@*", "*@stripe.com"],
      "action": "file_and_notify"
    }
  ],
  "default_category": "general",
  "actions": {
    "notify_immediately": { "type": "slack_or_email_digest", "target": "TBD" },
    "file_and_notify":     { "type": "label_and_folder", "target": "TBD" },
    "label_only":          { "type": "label_and_folder", "target": "TBD" }
  }
}
```

Rules for filling this in per business:
- `priority` controls sort order in the digest/dashboard, lower number = more urgent.
- `keywords` are matched against subject + first ~500 chars of body (case-insensitive).
- `sender_rules` support `*` wildcards and are checked before keywords (cheaper, more reliable).
- `action` must reference a key in `actions` — this is where "what actually happens"
  (Slack ping, move to folder, forward to someone) gets wired once you know your tools.
- Categories are checked in the order listed; first match wins. Put narrow/high-priority
  categories first, catch-alls last.
