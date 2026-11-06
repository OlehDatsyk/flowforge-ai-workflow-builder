"""Demonstration mode: transparent keyword and regex heuristics.

Nothing here calls an AI model, and every result is labelled ``provider: demo``
and ``simulated: true``. It exists so the product is usable without API keys.
"""
from __future__ import annotations

import re
from typing import Any

_STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "are", "it", "this", "that", "with", "as",
    "at", "be", "by", "from", "was", "were", "has", "have", "i", "we", "you", "my", "our", "your", "please",
}
_LABEL_HINTS: dict[str, list[str]] = {
    "high": ["urgent", "asap", "immediately", "critical", "outage", "down", "cannot", "can't", "blocked", "refund", "angry"],
    "urgent": ["urgent", "asap", "immediately", "critical", "outage"],
    "medium": ["soon", "issue", "problem", "error", "slow", "bug"],
    "low": ["question", "wondering", "minor", "whenever", "thanks", "feedback"],
    "billing": ["invoice", "charge", "charged", "refund", "payment", "billing", "subscription", "price"],
    "technical": ["error", "bug", "crash", "login", "password", "broken", "not working", "outage", "api"],
    "sales": ["pricing", "quote", "demo", "upgrade", "plan", "purchase", "buy"],
    "general": ["question", "information", "hello", "help"],
    "positive": ["great", "love", "excellent", "happy", "thanks", "amazing", "good"],
    "negative": ["bad", "terrible", "angry", "hate", "awful", "disappointed", "broken", "refund"],
    "neutral": ["okay", "fine", "information"],
    "spam": ["winner", "prize", "free money", "click here", "lottery"],
    "enterprise": ["enterprise", "corporation", "inc", "ltd", "gmbh", "company of", "employees"],
    "business": ["business", "company", "team", "startup", "llc", "ltd"],
    "personal": ["personal", "individual", "gmail", "hobby", "myself"],
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def demo_summarize(text: str, max_sentences: int = 2) -> dict:
    sentences = _sentences(text)
    words = [w for w in re.findall(r"[a-z']+", text.lower()) if w not in _STOP]
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(
        range(len(sentences)),
        key=lambda i: -sum(freq.get(w, 0) for w in re.findall(r"[a-z']+", sentences[i].lower())) / (len(sentences[i].split()) or 1),
    )
    chosen = sorted(ranked[: max(1, max_sentences)])
    return {"summary": " ".join(sentences[i] for i in chosen), "key_points": [sentences[i] for i in chosen]}


def demo_classify(text: str, labels: list[str]) -> dict:
    lowered = text.lower()
    scores = {}
    for label in labels:
        key = label.lower()
        hints = _LABEL_HINTS.get(key, []) + [key]
        scores[label] = sum(lowered.count(h) for h in hints)
    best = max(labels, key=lambda l: scores[l])
    total = sum(scores.values())
    if total == 0:
        return {"label": labels[0], "confidence": round(1 / len(labels), 2), "reasoning": "Demo heuristic: no keywords matched, so the first label was used."}
    return {"label": best, "confidence": round(scores[best] / total, 2), "reasoning": f"Demo heuristic: keyword matches {scores}."}


_FIELD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"e-?mail"), r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    (re.compile(r"amount|total|price|cost"), r"(?:amount|total|price|cost|due)[^\d£$€\n]{0,20}([£$€]?\s?\d[\d,]*(?:\.\d+)?)"),
    (re.compile(r"date"), r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\d{1,2} [A-Z][a-z]+ \d{4})\b"),
    (re.compile(r"phone"), r"\+?\d[\d\s()-]{7,}\d"),
]


def _label_pattern(field: str) -> str:
    words = re.split(r"[_\s-]+", field.strip())
    joined = r"[\s_-]*".join(re.escape(w) for w in words if w)
    return rf"{joined}(?:\s*(?:number|no\.?|#|name))?\s*[:=#-]\s*([^\n,;]+)"


def demo_extract(text: str, fields: list[str]) -> dict:
    data: dict[str, Any] = {}
    missing = []
    for field in fields:
        lowered = field.lower().replace("_", " ")
        value = None
        match = re.search(_label_pattern(field), text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
        else:
            for trigger, pattern in _FIELD_PATTERNS:
                if trigger.search(lowered):
                    found = re.search(pattern, text, re.IGNORECASE)
                    if found:
                        value = (found.group(1) if found.groups() else found.group(0)).strip()
                    break
        if value is None:
            missing.append(field)
        data[field] = value
    return {"data": data, "missing": missing}


def demo_generate(prompt: str) -> str:
    excerpt = prompt.strip().replace("\n", " ")
    if len(excerpt) > 280:
        excerpt = excerpt[:280] + "..."
    return (
        "[Demo text: no AI provider is configured, so no model generated this.] "
        f"A configured provider would respond to this prompt: \"{excerpt}\""
    )


def demo_decide(question: str, options: list[str], context: str) -> dict:
    result = demo_classify(f"{question} {context}", options)
    return {
        "decision": result["label"],
        "confidence": result["confidence"],
        "reasoning": result["reasoning"],
        "requires_human_review": True,
    }
