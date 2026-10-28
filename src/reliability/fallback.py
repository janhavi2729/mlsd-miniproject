"""Graceful degradation fallback path for provider resilience (Requirement A5)."""

from typing import Dict, Any, Optional
from src.observability.logging import get_logger
from src.contracts.determination import (
    Citation,
    DomainCategory,
    RoutingAction,
    RoutingDetermination,
    TokenUsage,
)

logger = get_logger("reliability.fallback")


def execute_graceful_fallback(
    run_id: str,
    correlation_id: str,
    complaint_text: str,
    claimed_category: str,
    entity_name: str,
    error_reason: str,
    prompt_version: str = "v2.0",
) -> RoutingDetermination:
    """
    Requirement A5: Graceful degradation along a defined fallback path.
    A run that did not complete must NOT be returned as a confident answer.
    Returns a transparently degraded routing determination with human escalation.
    """
    logger.warning(
        f"Activating graceful degradation fallback path for run {run_id}",
        extra_fields={"run_id": run_id, "error_reason": error_reason},
    )

    # Heuristic determination of safe routing target
    text_lower = complaint_text.lower()
    if "fixed deposit" in text_lower or claimed_category == "fixed_deposit" or "bank" in entity_name.lower():
        action = RoutingAction.REFER_TO_OTHER_REGULATOR
        domain = DomainCategory.OUT_OF_JURISDICTION
        target_reg = "Reserve Bank of India (RBI)"
        citations = [
            Citation(
                clause_id="RBI-IOS-08A",
                document_name="rbi_integrated_ombudsman_scheme_2021.txt",
                regulator="RBI",
                exact_quote="Clause 8A: Grounds of Complaint - Deposit Accounts and Fixed Deposits.",
                verified=True,
            )
        ]
    else:
        action = RoutingAction.ESCALATE_TO_HUMAN
        domain = DomainCategory.BROKER
        target_reg = "SEBI Investor Grievance Cell"
        citations = []

    return RoutingDetermination(
        run_id=run_id,
        correlation_id=correlation_id,
        domain=domain,
        routing_action=action,
        target_regulator=target_reg,
        target_entity=entity_name or "Unknown Regulated Entity",
        resolution_timeline_days=None,
        basis_and_justification=(
            f"[DEGRADED FALLBACK DETERMINATION] Primary reasoning model was unavailable ({error_reason}). "
            "To safeguard investor interests, this complaint has been routed along the pre-defined safety fallback path "
            "and escalated for mandatory human verification by a Grievance Redressal Officer."
        ),
        citations=citations,
        requires_human_escalation=True,
        escalation_reason=f"System Graceful Degradation Path: {error_reason}",
        verification_passed=False,
        token_usage=TokenUsage(),
        prompt_version=prompt_version,
    )
