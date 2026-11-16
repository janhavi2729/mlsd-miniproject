"""Agent 2: Regulatory Routing & Evidence Verification Agent (Requirement A1, A2, A3)."""

import time
from typing import Any, Dict, List, Optional
from src.agents.tools import AgentToolRegistry
from src.agents.verifier import verifier
from src.contracts.complaint import ComplaintSubmission
from src.contracts.determination import (
    AgentStepTrace,
    Citation,
    DomainCategory,
    RoutingAction,
    RoutingDetermination,
    TokenUsage,
)
from src.llm.client import llm_client
from src.observability.logging import get_logger

logger = get_logger("agents.routing")


class RoutingAgent:
    """
    Agent 2 in the multi-agent topology:
    Takes the structured hand-off from TriageAgent, performs targeted clause lookups
    and secondary corpus searches, verifies citation grounding against retrieved text,
    and produces the definitive routing determination.
    """

    def __init__(self, name: str = "RoutingAgent"):
        self.name = name

    def execute(
        self,
        submission: ComplaintSubmission,
        triage_hand_off: Dict[str, Any],
        tools: AgentToolRegistry,
        run_id: str,
        correlation_id: str,
        prompt_version: str = "v2.0",
        steps_list: Optional[List[AgentStepTrace]] = None,
    ) -> RoutingDetermination:
        start = time.time()
        logger.info(f"RoutingAgent executing adjudication for run {run_id}", extra_fields={"run_id": run_id})

        triage_output = triage_hand_off["triage_reasoning"]
        accumulated_passages = list(triage_hand_off.get("preliminary_passages", []))

        # 1. Targeted Clause Lookup (Tool 2)
        target_clause_id = None
        if triage_output.get("primary_regulator") == "RBI":
            target_clause_id = "RBI-IOS-08A"
        elif triage_output.get("domain") == "mutual_fund":
            target_clause_id = "SEBI-MF-REG-53B"
        elif triage_output.get("domain") == "broker":
            target_clause_id = "SEBI-CIR-05"
        elif triage_output.get("is_split_jurisdiction"):
            target_clause_id = "CROSS-REG-04"

        if target_clause_id:
            clause_doc = tools.clause_lookup(target_clause_id)
            if clause_doc:
                accumulated_passages.append(clause_doc)

        # 2. Call LLM for Adjudication and Routing
        adjudication = llm_client.adjudicate_and_route(
            triage_output=triage_output,
            retrieved_passages=accumulated_passages,
            complaint_text=submission.complaint_text,
            run_id=run_id,
            prompt_version=prompt_version,
        )

        target_clause = adjudication.get("clause_id", "SEBI-CIR-03")
        target_doc = adjudication.get("document_name", "sebi_scores_master_circular.txt")

        # Resolve exact quote from retrieved passages for citation grounding
        exact_quote = ""
        for p in accumulated_passages:
            if target_clause in p.get("clause_id", ""):
                lines = [l.strip() for l in p.get("text", "").split("\n") if l.strip()]
                exact_quote = lines[0] if lines else p.get("text", "")[:100]
                break

        if not exact_quote:
            # Fallback direct lookup to guarantee passage grounding
            lookup_res = tools.clause_lookup(target_clause)
            if lookup_res:
                accumulated_passages.append(lookup_res)
                exact_quote = lookup_res.get("text", "")[:120]

        citation = Citation(
            clause_id=target_clause,
            document_name=target_doc,
            regulator=adjudication.get("target_regulator", "SEBI"),
            exact_quote=exact_quote,
        )

        # 3. Evidence Verification (Requirement A3)
        citations_to_verify = [citation]
        all_verified, verified_citations, failure_reasons = verifier.verify_determination(
            citations=citations_to_verify,
            retrieved_passages=accumulated_passages,
            basis_text=adjudication.get("justification", ""),
        )

        # If verification fails, retry with a secondary search strategy or escalate
        if not all_verified:
            logger.warning(f"Initial citation verification failed for {target_clause}. Retrying with broader search...")
            fallback_passages = tools.corpus_search(query=target_clause, top_k=2)
            accumulated_passages.extend(fallback_passages)
            all_verified, verified_citations, failure_reasons = verifier.verify_determination(
                citations=citations_to_verify,
                retrieved_passages=accumulated_passages,
                basis_text=adjudication.get("justification", ""),
            )

        requires_escalation = adjudication.get("requires_escalation", False)
        escalation_reason = adjudication.get("escalation_reason")

        if not all_verified:
            # Requirement A3 & F7: An unverified answer must NOT be returned. Escalate!
            requires_escalation = True
            escalation_reason = f"Verification failure: {'; '.join(failure_reasons)}"
            action = RoutingAction.ESCALATE_TO_HUMAN
        else:
            action = RoutingAction(adjudication.get("routing_action", "assign-to-entity"))

        latency_ms = (time.time() - start) * 1000.0
        step_trace = AgentStepTrace(
            step_number=2,
            agent_name=self.name,
            action="regulatory_routing_and_verification",
            input_data={"target_clause": target_clause, "passages_count": len(accumulated_passages)},
            output_data={
                "routing_action": action.value,
                "verification_passed": all_verified,
                "requires_escalation": requires_escalation,
            },
            latency_ms=latency_ms,
            tokens=adjudication.get("token_usage"),
        )

        all_steps = (steps_list or []) + [step_trace]

        # Aggregate per-step LLM usage into the run total (feeds cost metrics, Requirement L5)
        step_usages = [s.tokens for s in all_steps if s.tokens is not None]
        run_usage = TokenUsage(
            prompt_tokens=sum(u.prompt_tokens for u in step_usages),
            completion_tokens=sum(u.completion_tokens for u in step_usages),
            total_tokens=sum(u.total_tokens for u in step_usages),
            estimated_cost_usd=sum(u.estimated_cost_usd for u in step_usages),
        )

        return RoutingDetermination(
            run_id=run_id,
            correlation_id=correlation_id,
            domain=triage_hand_off["domain"],
            routing_action=action,
            target_regulator=adjudication.get("target_regulator", "SEBI"),
            target_entity=adjudication.get("target_entity", submission.entity_name),
            resolution_timeline_days=adjudication.get("timeline_days"),
            basis_and_justification=adjudication.get("justification", ""),
            citations=verified_citations,
            requires_human_escalation=requires_escalation,
            escalation_reason=escalation_reason,
            verification_passed=all_verified,
            steps=all_steps,
            prompt_version=prompt_version,
            wall_clock_ms=sum(s.latency_ms for s in all_steps),
            token_usage=run_usage,
        )


routing_agent = RoutingAgent()
