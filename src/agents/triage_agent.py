"""Agent 1: Jurisdictional Triage & Ingestion Analysis Agent (Requirement A1, A2)."""

import time
from typing import Any, Dict
from src.agents.tools import AgentToolRegistry
from src.llm.client import llm_client
from src.contracts.complaint import ComplaintSubmission
from src.contracts.determination import AgentStepTrace, DomainCategory
from src.observability.logging import get_logger

logger = get_logger("agents.triage")


class TriageAgent:
    """
    Agent 1 in the multi-agent topology:
    Analyzes underlying financial instrument, transaction channel, entity type,
    and identifies primary vs secondary jurisdiction.
    Formulates initial hypothesis and structured hand-off to Agent 2.
    """

    def __init__(self, name: str = "TriageAgent"):
        self.name = name

    def execute(
        self,
        submission: ComplaintSubmission,
        tools: AgentToolRegistry,
        run_id: str,
        prompt_version: str = "v2.0",
    ) -> Dict[str, Any]:
        start = time.time()
        logger.info(f"TriageAgent started processing run {run_id}", extra_fields={"run_id": run_id})

        # 1. Use Tool 3: request_field_lookup to inspect fields
        category = tools.request_field_lookup("claimed_category")
        amount = tools.request_field_lookup("transaction_amount")
        entity = tools.request_field_lookup("entity_name")

        # 2. Call LLM reasoning layer for triage classification
        triage_reasoning = llm_client.triage_complaint(
            complaint_text=submission.complaint_text,
            claimed_category=category or submission.claimed_category,
            entity_name=entity or submission.entity_name,
            run_id=run_id,
            prompt_version=prompt_version,
        )

        # 3. Use Tool 1: corpus_search with query derived from reasoning
        search_q = triage_reasoning.get("search_query", submission.complaint_text[:100])
        preliminary_passages = tools.corpus_search(query=search_q, top_k=3)

        latency_ms = (time.time() - start) * 1000.0
        token_usage = triage_reasoning.get("token_usage")

        # Create step trace
        step_trace = AgentStepTrace(
            step_number=1,
            agent_name=self.name,
            action="jurisdictional_classification",
            input_data={
                "complaint_snippet": submission.complaint_text[:120],
                "claimed_category": category,
                "entity": entity,
            },
            output_data={
                "instrument": triage_reasoning.get("instrument"),
                "primary_regulator": triage_reasoning.get("primary_regulator"),
                "is_split": triage_reasoning.get("is_split_jurisdiction"),
                "retrieved_count": len(preliminary_passages),
            },
            latency_ms=latency_ms,
            tokens=token_usage,
        )

        hand_off_payload = {
            "triage_reasoning": triage_reasoning,
            "preliminary_passages": preliminary_passages,
            "step_trace": step_trace,
            "domain": DomainCategory(triage_reasoning.get("domain", "broker")),
        }
        return hand_off_payload


triage_agent = TriageAgent()
