# Email triage agent

A small, config-driven email classification agent. It reads a mailbox,
sorts each message into a category defined in a JSON file, alerts you on
the important ones, and remembers what it has already handled.

Runs on mock data out of the box, so you can try it without connecting
any real mailbox.

## How classification works

Checked in this order, cheapest first:

1. **Sender rules**: wildcard match on the address (`billing@*`, `*@stripe.com`)
2. **Sender memory**: a sender who has landed in one category 3+ times (70%+) is routed there
3. **Keywords**: matched against subject + body, in category priority order
4. **LLM fallback** (optional): a local model via LM Studio for ambiguous mail
5. **Default category**

Everything business-specific lives in `config/<business_id>.json`; the
engine never branches on business name. See `config/schema.md`.

## Layout

```
config/          one JSON file per business (+ schema.md, example_context.md)
connectors/      mail sources: mock (JSON file) and IMAP (with cert pinning)
classifier/      rule/keyword classifier + optional LM Studio fallback
actions/         alerts (CallMeBot, Meta Cloud API, Twilio), optional reply drafts
memory.py        SQLite per business: dedup, sender history, corrections
main.py          entry point
sample_data/     fictional sample emails
```

## Try it

```bash
python3 main.py acme_marketplace
python3 main.py demo_school
python3 main.py demo_school --llm     # also use a local LM Studio model (port 1234)
```

Alerts print in dry-run mode until credentials are set. Run it twice: the
second run processes nothing new, because memory remembers what was handled.

## Connecting a real mailbox

1. Set `"connector": "imap"` in the business config.
2. Copy `.env.example` to `.env` and fill in the `<BUSINESS_ID>_IMAP_*` values.
3. If the server uses a self-signed certificate, provide its SHA-256
   fingerprint; the connector pins it instead of disabling verification.

## Notifications

`action_type` in a config's `actions` block selects the channel:
`whatsapp_free` (CallMeBot), `whatsapp_meta` (Meta Cloud API), `whatsapp`
(Twilio), or `slack_or_email_digest` (currently prints; wire up your own).

## Reply drafting (optional)

Set `"draft_reply": true` on a category. The agent drafts a reply with
Gemini using `config/<business_id>_context.md` (start from
`config/example_context.md`) and sends the draft **to you** for review. It
never emails the original sender. Note that Gemini's free tier may use
inputs for product improvement; consider that before sending real customer data.

## Privacy notes

- `memory/*.db` and any exported notes contain real email metadata. They are git-ignored; keep it that way.
- Never commit `.env`.
- Email content is sent to third parties when you enable CallMeBot alerts (snippets) or reply drafting (bodies).

## Known limitations

- Keyword matching is whole-word, so it misses plurals and stems.
- Sender memory learns from the agent's own decisions, so early mistakes can reinforce themselves. Use `record_correction` to fix them.
- A failed alert is still recorded as processed and is not retried.
