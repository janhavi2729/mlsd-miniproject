"""Self-Verification Engine: Verifies every citation against retrieved passages (Requirement A3, F7)."""

from typing import Any, Dict, List, Tuple
from src.contracts.determination import Citation
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("agents.verifier")


class EvidenceVerifier:
    """
    Verifies that every citation in the routing determination resolves to actual retrieved text.
    If citations do not resolve to retrieved text, flags verification failure.
    """

    def verify_determination(
        self,
        citations: List[Citation],
        retrieved_passages: List[Dict[str, Any]],
        basis_text: str,
    ) -> Tuple[bool, List[Citation], List[str]]:
        """
        Returns (all_verified, updated_citations, failure_reasons).
        """
        if not citations:
            # If no citations were generated for a non-trivial routing, flag for escalation
            if "not-maintainable" not in basis_text.lower() and "escalat" not in basis_text.lower():
                metrics_collector.inc_counter("verification_failures_total", 1.0, {"reason": "missing_citations"})
                return False, [], ["No citations provided to support the determination."]
            return True, [], []

        retrieved_clause_ids = {p.get("clause_id", "").upper() for p in retrieved_passages}
        retrieved_full_text = " ".join(p.get("text", "") for p in retrieved_passages).lower()

        updated_citations: List[Citation] = []
        failure_reasons: List[str] = []
        all_ok = True

        for c in citations:
            clean_clause = c.clause_id.strip().upper()
            clause_found = False

            # 1. Check if clause exists in retrieved chunk metadata
            for rid in retrieved_clause_ids:
                if clean_clause in rid or rid in clean_clause:
                    clause_found = True
                    break

            # 2. Check if quote text exists in retrieved body
            quote_clean = c.exact_quote.strip().lower()
            quote_grounded = True
            if quote_clean and len(quote_clean) > 15:
                # Substring or token overlap check
                tokens = [t for t in quote_clean.split() if len(t) > 3]
                matched_tokens = [t for t in tokens if t in retrieved_full_text]
                if tokens and (len(matched_tokens) / len(tokens)) < 0.5:
                    quote_grounded = False

            if clause_found and quote_grounded:
                c.verified = True
                updated_citations.append(c)
            else:
                c.verified = False
                updated_citations.append(c)
                all_ok = False
                reason = f"Citation {c.clause_id} failed verification against retrieved passages."
                failure_reasons.append(reason)
                logger.warning(reason, extra_fields={"clause_id": c.clause_id})

        if not all_ok:
            metrics_collector.inc_counter("verification_failures_total", 1.0, {"reason": "unresolved_citations"})
        else:
            metrics_collector.inc_counter("verification_success_total", 1.0)

        return all_ok, updated_citations, failure_reasons


verifier = EvidenceVerifier()
