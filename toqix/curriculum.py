"""TOQIX all-in-one curriculum — loader + domain detection.

The curriculum (data/curriculum/domains.json) is how the owner's
"train it on everything" instruction is implemented in practice:
a taxonomy of all major video domains with bilingual example prompts
and caption templates. The prompt engine uses it for domain detection
and template choice; the Studio exposes it for balanced batch jobs;
the flywheel curates training data across the same domains.
"""

from __future__ import annotations

import json
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def load_domains() -> list[dict]:
    data = json.loads(config.DOMAINS_PATH.read_text(encoding="utf-8"))
    return data["domains"]


def get_domain(domain_id: str | None) -> dict | None:
    if not domain_id:
        return None
    for domain in load_domains():
        if domain["id"] == domain_id:
            return domain
    return None


def detect_domain(text: str) -> dict | None:
    """Score the text against every domain's keyword list (English +
    Roman Urdu keywords) and return the best-matching domain, or None."""
    low = f" {text.lower()} "
    best, best_hits = None, 0
    for domain in load_domains():
        hits = sum(1 for kw in domain.get("keywords", []) if kw.lower() in low)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best if best_hits > 0 else None
