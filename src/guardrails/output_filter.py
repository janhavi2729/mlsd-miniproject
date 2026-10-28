"""Output filtering and unauthorized determination prevention (Requirement L4)."""

import re
from typing import Tuple, List
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("guardrails.output_filter")

# Patterns of unauthorized determinations the system is strictly barred from issuing
UNAUTHORIZED_PATTERNS = [
    (re.compile(r"\b(i\s+hereby\s+order|the\s+court\s+orders|mandatory\s+damages\s+awarded)\b", re.IGNORECASE), "judicial_award_prohibited"),
    (re.compile(r"\b(guaranteed\s+refund|guarantee\s+that\s+your\s+money\s+will\s+be\s+returned)\b", re.IGNORECASE), "unauthorized_settlement_guarantee"),
    (re.compile(r"\b(you\s+should\s+(buy|sell|short|accumulate)\s+(shares|stocks|options|futures))\b", re.IGNORECASE), "financial_trading_advice_prohibited"),
    (re.compile(r"\b(we\s+have\s+seized|freezing\s+the\s+bank\s+accounts\s+immediately)\b", re.IGNORECASE), "enforcement_action_prohibited"),
]


def filter_agent_output(output_text: str) -> Tuple[bool, List[str], str]:
    """
    Checks if agent generated text contains unauthorized regulatory assertions or advice.
    Returns (is_compliant, violated_policies, sanitized_or_redacted_text).
    """
    if not output_text:
        return True, [], ""

    violations = []
    sanitized = output_text

    for pattern, violation_type in UNAUTHORIZED_PATTERNS:
        if pattern.search(sanitized):
            violations.append(violation_type)
            # Redact unauthorized phrase
            sanitized = pattern.sub("[REDACTED: UNAUTHORIZED STATUTORY CLAIM]", sanitized)

    if violations:
        metrics_collector.inc_counter("guardrails_output_violations_blocked_total", 1.0)
        logger.warning(
            f"Output filter blocked unauthorized statements: {violations}",
            extra_fields={"violations": violations},
        )
        return False, violations, sanitized

    return True, [], sanitized
