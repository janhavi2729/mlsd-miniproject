"""Multi-Agent Reasoning Graph & Topology Orchestration (Requirements A1, A2, A3, A5, L4)."""

import time
import uuid
from typing import Dict, Any, Optional

from src.agents.triage_agent import triage_agent
from src.agents.routing_agent import routing_agent
from src.agents.tools import AgentToolRegistry
from src.config import settings
from src.contracts.complaint import ComplaintSubmission
from src.contracts.determination import RoutingDetermination
from src.guardrails.output_filter import filter_agent_output
from src.guardrails.prompt_injection import check_prompt_injection
from src.guardrails.toxicity import check_toxicity
from src.observability.logging import get_logger, set_request_context
from src.observability.metrics import metrics_collector
from src.observability.tracing import run_reconstruction_store
from src.reliability.circuit_breaker import circuit_breaker, CircuitBreakerOpenException
from src.reliability.fallback import execute_graceful_fallback
from src.reliability.retry import execute_with_retry

logger = get_logger("agents.graph")


class MultiAgentGraph:
    """
    Reasoning Graph Topology:
    [Submission]
         │
         ▼
    [Guardrails Check: Injection & Toxicity]
         │
         ▼
    [Agent 1: Triage & Jurisdictional Analysis] (Tools: request_field_lookup, corpus_search)
         │  (Hand-off Payload)
         ▼
    [Agent 2: Regulatory Routing & Evidence Verification] (Tools: clause_lookup, corpus_search)
         │
         ▼
    [Evidence Grounding Verification] (Pass: proceed | Fail: retry or Escalate)
         │
         ▼
    [Output Guardrail Filter]
         │
         ▼
    [Final Routing Determination & Telemetry Reconstruction Store]

    Bounds:
    - Max steps: settings.MAX_AGENT_STEPS (6)
    - Max tool calls: settings.MAX_TOOL_CALLS (8)
    - Wall-clock timeout: settings.AGENT_TIMEOUT_SECONDS (25.0s)
    """

    def __init__(self):
        self.max_steps = settings.MAX_AGENT_STEPS
        self.max_tool_calls = settings.MAX_TOOL_CALLS
        self.timeout_seconds = settings.AGENT_TIMEOUT_SECONDS

    def run(
        self,
        submission: ComplaintSubmission,
        run_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> RoutingDetermination:
        wall_clock_start = time.time()
        active_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        active_corr_id = correlation_id or submission.correlation_id or f"corr_{uuid.uuid4().hex[:8]}"
        p_version = prompt_version or settings.ACTIVE_PROMPT_VERSION

        set_request_context(correlation_id=active_corr_id, run_id=active_run_id)
        logger.info(
            f"Initiating multi-agent run {active_run_id}",
            extra_fields={"run_id": active_run_id, "correlation_id": active_corr_id, "prompt_version": p_version},
        )

        # Step 0: Input Guardrails Screener (Requirement L4)
        has_inj, inj_patterns = check_prompt_injection(submission.complaint_text)
        has_tox, tox_categories = check_toxicity(submission.complaint_text)

        if has_inj:
            logger.warning(f"Run {active_run_id} blocked: prompt injection attempt detected")
            det = execute_graceful_fallback(
                run_id=active_run_id,
                correlation_id=active_corr_id,
                complaint_text=submission.complaint_text,
                claimed_category=submission.claimed_category,
                entity_name=submission.entity_name,
                error_reason=f"Security Guardrail: Input blocked due to prompt injection attempt ({inj_patterns})",
                prompt_version=p_version,
            )
            self._record_telemetry(active_run_id, det, wall_clock_start)
            return det

        # Initialize Agent Tools with execution tracking
        tools = AgentToolRegistry(submission=submission, run_id=active_run_id)

        try:
            # Check Circuit Breaker before calling reasoning providers (Requirement A5)
            if not circuit_breaker.can_execute():
                logger.warning("Circuit breaker is OPEN. Executing graceful degradation path.")
                det = execute_graceful_fallback(
                    run_id=active_run_id,
                    correlation_id=active_corr_id,
                    complaint_text=submission.complaint_text,
                    claimed_category=submission.claimed_category,
                    entity_name=submission.entity_name,
                    error_reason="Provider Circuit Breaker OPEN (consecutive failures exceeded)",
                    prompt_version=p_version,
                )
                self._record_telemetry(active_run_id, det, wall_clock_start)
                return det

            # Step 1: Execute Agent 1 (TriageAgent) with retry protection
            triage_hand_off = execute_with_retry(
                func=lambda: triage_agent.execute(
                    submission=submission,
                    tools=tools,
                    run_id=active_run_id,
                    prompt_version=p_version,
                ),
                max_retries=settings.LLM_MAX_RETRIES,
                step_name="triage_agent_execution",
            )

            # Step 2: Enforce loop & timeout bounds (Requirement A1)
            if (time.time() - wall_clock_start) > self.timeout_seconds:
                raise TimeoutError(f"Agent execution exceeded wall-clock limit ({self.timeout_seconds}s)")

            if tools.tool_call_count > self.max_tool_calls:
                raise RuntimeError(f"Agent exceeded maximum tool call limit ({self.max_tool_calls})")

            # Step 3: Execute Agent 2 (RoutingAgent)
            determination = execute_with_retry(
                func=lambda: routing_agent.execute(
                    submission=submission,
                    triage_hand_off=triage_hand_off,
                    tools=tools,
                    run_id=active_run_id,
                    correlation_id=active_corr_id,
                    prompt_version=p_version,
                    steps_list=[triage_hand_off["step_trace"]],
                ),
                max_retries=settings.LLM_MAX_RETRIES,
                step_name="routing_agent_execution",
            )

            # Circuit breaker records successful run
            circuit_breaker.record_success()

            # Step 4: Output Guardrails Filter (Requirement L4)
            is_compliant, violated_policies, sanitized_justification = filter_agent_output(
                determination.basis_and_justification
            )
            if not is_compliant:
                determination.basis_and_justification = sanitized_justification
                determination.requires_human_escalation = True
                determination.escalation_reason = (
                    f"Output policy violation redacted: {violated_policies}. Mandatory human review."
                )

            determination.wall_clock_ms = (time.time() - wall_clock_start) * 1000.0
            self._record_telemetry(active_run_id, determination, wall_clock_start)
            return determination

        except (CircuitBreakerOpenException, ConnectionError, TimeoutError, Exception) as exc:
            logger.error(
                f"Agent execution error on run {active_run_id}: {exc}. Triggering graceful degradation fallback.",
                extra_fields={"run_id": active_run_id, "error": str(exc)},
            )
            circuit_breaker.record_failure()
            det = execute_graceful_fallback(
                run_id=active_run_id,
                correlation_id=active_corr_id,
                complaint_text=submission.complaint_text,
                claimed_category=submission.claimed_category,
                entity_name=submission.entity_name,
                error_reason=f"Runtime exception: {str(exc)}",
                prompt_version=p_version,
            )
            self._record_telemetry(active_run_id, det, wall_clock_start)
            return det

    def _record_telemetry(self, run_id: str, det: RoutingDetermination, start_time: float):
        total_time_s = time.time() - start_time
        det_dict = det.to_dict()

        # Save to full run reconstruction store (Requirement D5)
        run_reconstruction_store.save_run(run_id, det_dict)

        # Update Prometheus metrics
        metrics_collector.inc_counter(
            "agent_runs_total",
            1.0,
            {"domain": det_dict["domain"], "action": det_dict["routing_action"]},
        )
        metrics_collector.observe_histogram(
            "agent_run_duration_seconds",
            total_time_s,
            {"domain": det_dict["domain"], "action": det_dict["routing_action"]},
        )
        metrics_collector.inc_counter(
            "agent_cost_usd_total",
            det.token_usage.estimated_cost_usd,
        )


multi_agent_graph = MultiAgentGraph()
