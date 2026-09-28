"""
classifier/classifier.py — turns one email + a business's category config
into a category decision.

Order of precedence (cheapest/most reliable first):
1. Sender rules (explicit wildcard match, e.g. "billing@*")
2. Sender bias from memory (this sender has consistently landed in category X)
3. Keyword match against subject + body
4. Optional LLM fallback (local LM Studio model) for anything still ambiguous
5. default_category from config

This keeps 90%+ of classification essentially free (string matching),
and only calls out to a model for the genuinely unclear cases — important
given the laptop shouldn't be doing heavy inference locally.
"""

import fnmatch
import re
from typing import Dict, Optional
from memory import AgentMemory


class Classification:
    def __init__(self, category_id: str, matched_by: str, category_config: dict):
        self.category_id = category_id
        self.matched_by = matched_by
        self.config = category_config

    def __repr__(self):
        return f"<Classification {self.category_id} via {self.matched_by}>"


def _sender_matches(sender: str, patterns) -> bool:
    sender = sender.lower()
    return any(fnmatch.fnmatch(sender, p.lower()) for p in patterns)


def _keyword_matches(text: str, keywords) -> bool:
    text = text.lower()
    return any(re.search(r"\b" + re.escape(kw.lower()) + r"\b", text) for kw in keywords)


def classify_email(email: Dict, business_config: dict, memory: AgentMemory,
                    llm_fallback=None) -> Classification:
    categories = business_config["categories"]
    cat_by_id = {c["id"]: c for c in categories}
    sender = email.get("sender", "")
    text_blob = f"{email.get('subject', '')} {email.get('body', '')}"

    # 1. explicit sender rules, in category priority order
    for cat in sorted(categories, key=lambda c: c["priority"]):
        if cat.get("sender_rules") and _sender_matches(sender, cat["sender_rules"]):
            return Classification(cat["id"], "sender_rule", cat)

    # 2. sender bias from memory (past pattern for this exact sender)
    biased_cat_id = memory.get_sender_bias(sender)
    if biased_cat_id and biased_cat_id in cat_by_id:
        return Classification(biased_cat_id, "sender_memory", cat_by_id[biased_cat_id])

    # 3. keyword match, in priority order
    for cat in sorted(categories, key=lambda c: c["priority"]):
        if cat.get("keywords") and _keyword_matches(text_blob, cat["keywords"]):
            return Classification(cat["id"], "keyword", cat)

    # 4. optional LLM fallback for ambiguous mail (e.g. LM Studio local model)
    if llm_fallback is not None:
        try:
            suggested = llm_fallback(email, categories)
            if suggested in cat_by_id:
                return Classification(suggested, "llm", cat_by_id[suggested])
        except Exception:
            pass  # fail quietly to default rather than break the pipeline

    # 5. default
    default_id = business_config["default_category"]
    return Classification(default_id, "default", cat_by_id[default_id])
