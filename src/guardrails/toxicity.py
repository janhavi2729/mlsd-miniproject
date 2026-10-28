"""Toxicity and abusive language screener for input and output (Requirement L4)."""

import re
from typing import Tuple, List
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("guardrails.toxicity")

TOXIC_TERMS = [
    r"\b(kill|murder|bomb|terrorist|assassinate)\b",
    r"\b(bastard|bitch|asshole|idiot|scumbag)\b",
    r"\b(cheat|thief|fraudster|looter)\s+(deserves\s+to\s+die)\b",
]

TOXIC_REGEX = [re.compile(p, re.IGNORECASE) for p in TOXIC_TERMS]


def check_toxicity(text: str) -> Tuple[bool, List[str]]:
    """
    Returns (is_toxic, detected_categories).
    """
    if not text:
        return False, []

    detected = []
    for reg in TOXIC_REGEX:
        if reg.search(text):
            detected.append("abusive_or_violent_language")
            break

    if detected:
        metrics_collector.inc_counter("guardrails_toxicity_detected_total", 1.0)
        logger.warning("Toxic content detected in grievance payload", extra_fields={"categories": detected})
        return True, detected

    return False, []
