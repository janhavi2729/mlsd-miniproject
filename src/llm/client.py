"""Unified LLM Client abstraction with timeout, retries, and provider switching (Requirement A1, A5, D4).

Providers:
- "stub":   deterministic keyword provider (offline demos, CI, load tests).
- "gemini": Google Gemini via REST (needs LLM_API_KEY).
- "openai": OpenAI or any OpenAI-compatible endpoint (Groq, OpenRouter, Ollama, ...)
            via LLM_BASE_URL. LLM_API_KEY is optional when LLM_BASE_URL is set (e.g. local Ollama).
"""

import threading
import time
from typing import Any, Dict, List, Optional

from src.config import settings
from src.contracts.determination import DomainCategory, RoutingAction
from src.llm.cost_tracker import cost_ledger
from src.llm.prompts import build_routing_messages, build_triage_messages
from src.llm.providers import DEFAULT_MODELS, call_provider
from src.llm.stub_provider import stub_llm
from src.observability.logging import get_logger

logger = get_logger("llm.client")

REAL_PROVIDERS = ("gemini", "openai")
VALID_REGULATORS = {"SEBI", "RBI", "IRDAI", "PFRDA", "MCA", "MULTI_REGULATOR", "NONE_UNREGULATED"}
VALID_DOMAINS = {d.value for d in DomainCategory}
VALID_ACTIONS = {a.value for a in RoutingAction}


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def normalize_triage(raw: Dict[str, Any], complaint_text: str) -> Dict[str, Any]:
    """Coerces model output into the hand-off contract the agents expect."""
    regulator = str(raw.get("primary_regulator", "")).strip().upper().replace(" ", "_")
    if regulator not in VALID_REGULATORS:
        regulator = "MULTI_REGULATOR" if _as_bool(raw.get("is_split_jurisdiction")) else "SEBI"

    domain = str(raw.get("domain", "")).strip().lower().replace(" ", "_")
    if domain == "out_of_jurisdiction":
        domain = "out-of-jurisdiction"
    if domain not in VALID_DOMAINS:
        domain = "broker" if regulator == "SEBI" else "out-of-jurisdiction"
    if regulator != "SEBI":
        domain = "out-of-jurisdiction"

    return {
        "instrument": str(raw.get("instrument", "Unknown")),
        "entity_type": str(raw.get("entity_type", "Unknown")),
        "primary_regulator": regulator,
        "domain": domain,
        "is_sebi_jurisdiction": regulator == "SEBI",
        "is_split_jurisdiction": _as_bool(raw.get("is_split_jurisdiction")) or regulator == "MULTI_REGULATOR",
        "recommended_tools": ["corpus_search", "clause_lookup"],
        "search_query": str(raw.get("search_query") or complaint_text[:100]),
        "reasoning": str(raw.get("reasoning", "")),
    }


def normalize_adjudication(raw: Dict[str, Any], retrieved_passages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerces model output into the routing contract. Unknown actions fail safe to human escalation."""
    action = str(raw.get("routing_action", "")).strip().lower()
    requires_escalation = _as_bool(raw.get("requires_escalation"))
    escalation_reason = raw.get("escalation_reason") or None
    if action not in VALID_ACTIONS:
        escalation_reason = f"Model returned unknown routing_action {action!r}; human review required."
        action = RoutingAction.ESCALATE_TO_HUMAN.value
        requires_escalation = True
    if action == RoutingAction.ESCALATE_TO_HUMAN.value:
        requires_escalation = True

    timeline = raw.get("timeline_days")
    try:
        timeline = int(timeline) if timeline not in (None, "", "null") else None
    except (TypeError, ValueError):
        timeline = None

    clause_id = str(raw.get("clause_id", "")).strip().upper()
    document_name = raw.get("document_name")
    # Fill document_name from the passage the model cited, if it named a retrieved clause.
    for p in retrieved_passages:
        if clause_id and clause_id == str(p.get("clause_id", "")).upper():
            document_name = p.get("document_name", document_name)
            break

    return {
        "routing_action": action,
        "target_regulator": str(raw.get("target_regulator", "SEBI")),
        "target_entity": str(raw.get("target_entity", "")),
        "timeline_days": timeline,
        "requires_escalation": requires_escalation,
        "escalation_reason": escalation_reason,
        "justification": str(raw.get("justification", "")),
        # An unknown or missing clause_id is passed through as-is so the EvidenceVerifier rejects it.
        "clause_id": clause_id or "UNCITED",
        "document_name": document_name or "unknown",
    }


class LLMClient:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.strip().lower()
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.timeout = settings.LLM_TIMEOUT_SECONDS
        self._rate_lock = threading.Lock()
        self._next_slot = 0.0

        model = settings.LLM_MODEL
        if self.provider in REAL_PROVIDERS and (not model or model.startswith("stub")):
            model = DEFAULT_MODELS[self.provider]
        self.model_name = model

        self.use_real_llm = self.provider in REAL_PROVIDERS and bool(
            self._has_usable_key()
        )
        if self.provider not in REAL_PROVIDERS + ("stub",):
            logger.warning(f"Unknown LLM_PROVIDER '{self.provider}'; using deterministic stub provider.")
        elif self.provider in REAL_PROVIDERS and not self.use_real_llm:
            logger.warning(
                f"LLM_PROVIDER={self.provider} but LLM_API_KEY is not set; "
                "falling back to the deterministic stub provider. Set LLM_API_KEY to use the real model."
            )
        else:
            logger.info(f"LLM client active: provider={self.active_provider}, model={self.active_model}")

    def _has_usable_key(self) -> bool:
        key = (self.api_key or "").strip()
        if key and key != "your_api_key_here":
            return True
        # OpenAI-compatible local servers (e.g. Ollama) don't need a key.
        return self.provider == "openai" and bool(self.base_url)

    @property
    def active_provider(self) -> str:
        return self.provider if self.use_real_llm else "stub"

    @property
    def active_model(self) -> str:
        return self.model_name if self.use_real_llm else stub_llm.__class__.__name__

    def describe(self) -> Dict[str, Any]:
        return {"configured_provider": self.provider, "active_provider": self.active_provider,
                "model": self.active_model}

    def _throttle(self) -> None:
        """Spaces out requests to stay under LLM_MAX_RPM (shared across worker threads)."""
        if settings.LLM_MAX_RPM <= 0:
            return
        interval = 60.0 / settings.LLM_MAX_RPM
        with self._rate_lock:
            wait = self._next_slot - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._next_slot = max(time.monotonic(), self._next_slot) + interval

    def _call_real(self, system: str, user: str):
        # Honour the demo fail switch (Demonstration Item 8) for real providers too.
        if stub_llm.fail_mode:
            raise ConnectionError(stub_llm.failure_error_message)
        self._throttle()
        return call_provider(
            provider=self.provider,
            system=system,
            user=user,
            model=self.model_name,
            api_key=self.api_key,
            timeout=self.timeout,
            base_url=self.base_url,
        )

    def triage_complaint(
        self,
        complaint_text: str,
        claimed_category: str,
        entity_name: str,
        run_id: str,
        prompt_version: str = "v2.0",
    ) -> Dict[str, Any]:
        """Invokes the model for Triage Agent reasoning."""
        start_time = time.time()

        if self.use_real_llm:
            system, user = build_triage_messages(prompt_version, complaint_text, claimed_category, entity_name)
            raw, prompt_tok, comp_tok = self._call_real(system, user)
            res = normalize_triage(raw, complaint_text)
        else:
            res = stub_llm.generate_triage(
                complaint_text=complaint_text,
                claimed_category=claimed_category,
                entity_name=entity_name,
                prompt_version=prompt_version,
            )
            prompt_tok = res.pop("prompt_tokens", 300)
            comp_tok = res.pop("completion_tokens", 100)

        duration_ms = (time.time() - start_time) * 1000.0
        token_usage = cost_ledger.record_call(
            run_id=run_id,
            step_name="triage_classification",
            agent_name="TriageAgent",
            prompt_tokens=prompt_tok,
            completion_tokens=comp_tok,
        )
        res["token_usage"] = token_usage
        res["latency_ms"] = duration_ms
        res["llm_provider"] = self.active_provider
        res["llm_model"] = self.active_model
        return res

    def adjudicate_and_route(
        self,
        triage_output: Dict[str, Any],
        retrieved_passages: List[Dict[str, Any]],
        complaint_text: str,
        run_id: str,
        prompt_version: str = "v2.0",
    ) -> Dict[str, Any]:
        """Invokes the model for Adjudication and Routing reasoning."""
        start_time = time.time()

        if self.use_real_llm:
            system, user = build_routing_messages(prompt_version, triage_output, retrieved_passages, complaint_text)
            raw, prompt_tok, comp_tok = self._call_real(system, user)
            res = normalize_adjudication(raw, retrieved_passages)
        else:
            res = stub_llm.generate_adjudication(
                triage_output=triage_output,
                retrieved_passages=retrieved_passages,
                complaint_text=complaint_text,
                prompt_version=prompt_version,
            )
            prompt_tok = res.pop("prompt_tokens", 450)
            comp_tok = res.pop("completion_tokens", 150)

        duration_ms = (time.time() - start_time) * 1000.0
        token_usage = cost_ledger.record_call(
            run_id=run_id,
            step_name="adjudication_routing",
            agent_name="RoutingAgent",
            prompt_tokens=prompt_tok,
            completion_tokens=comp_tok,
        )
        res["token_usage"] = token_usage
        res["latency_ms"] = duration_ms
        res["llm_provider"] = self.active_provider
        res["llm_model"] = self.active_model
        return res


llm_client = LLMClient()
