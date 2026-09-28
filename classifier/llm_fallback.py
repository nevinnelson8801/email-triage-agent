"""
classifier/llm_fallback.py — optional local-model fallback via LM Studio.

LM Studio exposes an OpenAI-compatible API at http://localhost:1234/v1
when you start its local server. This function is a thin wrapper that:
  - only runs when explicitly enabled (nothing calls a model by default)
  - sends the email + the list of valid category ids
  - asks for a single category id back, nothing else
  - times out fast and fails silently (classifier.py falls back to "default"
    if this raises or returns garbage)

This keeps heavy inference OFF your laptop's main flow — it's a local
call to whatever model you've loaded in LM Studio, and only fires for
emails that didn't match any rule or keyword.
"""

import json
import urllib.request
import urllib.error

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"


def classify_with_lm_studio(email: dict, categories: list, model: str = "local-model",
                             timeout: float = 5.0) -> str:
    category_lines = "\n".join(
        f"- {c['id']}: {c['description']}" for c in categories
    )
    prompt = (
        "Classify this email into exactly one category id from the list below. "
        "Reply with ONLY the category id, nothing else.\n\n"
        f"Categories:\n{category_lines}\n\n"
        f"Email subject: {email.get('subject', '')}\n"
        f"Email body: {email.get('body', '')[:500]}\n\n"
        "Category id:"
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 20,
    }

    req = urllib.request.Request(
        LM_STUDIO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        text = result["choices"][0]["message"]["content"].strip()
        # strip common formatting a small model might add
        return text.strip('"').strip("'").strip(".").split()[0] if text else ""
