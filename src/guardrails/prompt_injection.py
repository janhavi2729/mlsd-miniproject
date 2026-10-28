"""Prompt injection detection and input sanitization (Requirement L4)."""

import re
from typing import Tuple, List
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("guardrails.prompt_injection")

# Heuristic and pattern-based prompt injection detection rules
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+rules?", re.IGNORECASE),
    re.compile(r"system\s*override", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(an?\s+)?unrestricted", re.IGNORECASE),
    re.compile(r"do\s+anything\s+now", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"dan\s+mode", re.IGNORECASE),
    re.compile(r"forget\s+all\s+instructions", re.IGNORECASE),
    re.compile(r"bypass\s+regulatory\s+check", re.IGNORECASE),
    re.compile(r"approve\s+this\s+immediately\s+without\s+verification", re.IGNORECASE),
    re.compile(r"<\s*script\s*>", re.IGNORECASE),
    re.compile(r"\{\{.*\}\}", re.IGNORECASE),
]


def check_prompt_injection(text: str) -> Tuple[bool, List[str]]:
    """
    Scans untrusted user text for prompt injection patterns.
    Returns (is_injection_detected, matched_patterns).
    """
    if not text:
        return False, []

    matches = []
    for pattern in INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            matches.append(match.group(0))

    if matches:
        metrics_collector.inc_counter("guardrails_prompt_injections_blocked_total", 1.0)
        logger.warning(
            f"Prompt injection pattern detected: {matches}",
            extra_fields={"matched_patterns": matches},
        )
        return True, matches

    return False, []
