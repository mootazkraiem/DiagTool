"""RAG retrieval — keyword-match over attack_kb.json.

No vector DB required: we tokenise keywords from the alert context and score
each KB entry by overlap with the entry's keyword list.  The top match is
returned so the LLM can ground its explanation in the known attack taxonomy.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_KB_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "attack_kb.json"
_kb: list[dict[str, Any]] | None = None


def _load() -> list[dict[str, Any]]:
    global _kb
    if _kb is None:
        _kb = json.loads(_KB_PATH.read_text(encoding="utf-8"))
    return _kb


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[\s,_=.;:|/\\-]+", text.lower())) - {"", "the", "a", "an", "of", "in", "on"}


def retrieve(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Return the best-matching KB entry for the given alert dict.

    Builds a query bag-of-words from: can_id, attack_type, dominant_detection_layer,
    severity, reason.  Scores KB entries by keyword overlap (hits / total_keywords).
    Returns None if nothing scores > 0.
    """
    query_parts = " ".join(filter(None, [
        str(alert.get("can_id", "")),
        str(alert.get("attack_type", "")),
        str(alert.get("dominant_detection_layer", "")),
        str(alert.get("severity", "")),
        str(alert.get("reason", "")),
    ]))
    query_tokens = _tokens(query_parts)

    best_score = 0.0
    best_entry: dict[str, Any] | None = None

    for entry in _load():
        keywords: list[str] = entry.get("keywords", [])
        if not keywords:
            continue
        hits = sum(1 for kw in keywords if kw in query_tokens or any(kw in qt for qt in query_tokens))
        score = hits / len(keywords)
        if score > best_score:
            best_score = score
            best_entry = entry

    return best_entry if best_score > 0 else None
