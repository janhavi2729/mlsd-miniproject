"""Data contracts for routing determination and agent execution trace."""

from enum import Enum
from typing import Any, Dict, List, Optional


class RoutingAction(str, Enum):
    ASSIGN_TO_ENTITY = "assign-to-entity"
    REFER_TO_OTHER_REGULATOR = "refer-to-other-regulator"
    NOT_MAINTAINABLE = "not-maintainable"
    ESCALATE_TO_HUMAN = "escalate-to-human"


class DomainCategory(str, Enum):
    BROKER = "broker"
    MUTUAL_FUND = "mutual_fund"
    DEPOSITORY = "depository"
    REGISTRAR = "registrar"
    LISTED_COMPANY = "listed_company"
    OUT_OF_JURISDICTION = "out-of-jurisdiction"


class Citation:
    def __init__(
        self,
        clause_id: str,
        document_name: str,
        regulator: str,
        exact_quote: str,
        verified: bool = False,
    ):
        self.clause_id = clause_id
        self.document_name = document_name
        self.regulator = regulator
        self.exact_quote = exact_quote
        self.verified = verified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "document_name": self.document_name,
            "regulator": self.regulator,
            "exact_quote": self.exact_quote,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Citation":
        return cls(
            clause_id=data.get("clause_id", ""),
            document_name=data.get("document_name", ""),
            regulator=data.get("regulator", ""),
            exact_quote=data.get("exact_quote", ""),
            verified=data.get("verified", False),
        )


class TokenUsage:
    def __init__(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens or (prompt_tokens + completion_tokens)
        self.estimated_cost_usd = estimated_cost_usd

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenUsage":
        return cls(
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            estimated_cost_usd=data.get("estimated_cost_usd", 0.0),
        )


class AgentStepTrace:
    def __init__(
        self,
        step_number: int,
        agent_name: str,
        action: str,
        input_data: Any,
        output_data: Any,
        latency_ms: float,
        tokens: Optional[TokenUsage] = None,
    ):
        self.step_number = step_number
        self.agent_name = agent_name
        self.action = action
        self.input_data = input_data
        self.output_data = output_data
        self.latency_ms = latency_ms
        self.tokens = tokens or TokenUsage()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "agent_name": self.agent_name,
            "action": self.action,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "latency_ms": round(self.latency_ms, 2),
            "tokens": self.tokens.to_dict(),
        }


class RoutingDetermination:
    """Published specification of final determination produced by the agent system (F5, F6, F7)."""

    def __init__(
        self,
        run_id: str,
        correlation_id: str,
        domain: DomainCategory,
        routing_action: RoutingAction,
        target_regulator: str,
        target_entity: str,
        resolution_timeline_days: Optional[int],
        basis_and_justification: str,
        citations: List[Citation],
        requires_human_escalation: bool = False,
        escalation_reason: Optional[str] = None,
        verification_passed: bool = True,
        token_usage: Optional[TokenUsage] = None,
        steps: Optional[List[AgentStepTrace]] = None,
        prompt_version: str = "v2.0",
        wall_clock_ms: float = 0.0,
    ):
        self.run_id = run_id
        self.correlation_id = correlation_id
        self.domain = domain
        self.routing_action = routing_action
        self.target_regulator = target_regulator
        self.target_entity = target_entity
        self.resolution_timeline_days = resolution_timeline_days
        self.basis_and_justification = basis_and_justification
        self.citations = citations
        self.requires_human_escalation = requires_human_escalation
        self.escalation_reason = escalation_reason
        self.verification_passed = verification_passed
        self.token_usage = token_usage or TokenUsage()
        self.steps = steps or []
        self.prompt_version = prompt_version
        self.wall_clock_ms = wall_clock_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "domain": self.domain.value if isinstance(self.domain, DomainCategory) else str(self.domain),
            "routing_action": self.routing_action.value if isinstance(self.routing_action, RoutingAction) else str(self.routing_action),
            "target_regulator": self.target_regulator,
            "target_entity": self.target_entity,
            "resolution_timeline_days": self.resolution_timeline_days,
            "basis_and_justification": self.basis_and_justification,
            "citations": [c.to_dict() for c in self.citations],
            "requires_human_escalation": self.requires_human_escalation,
            "escalation_reason": self.escalation_reason,
            "verification_passed": self.verification_passed,
            "token_usage": self.token_usage.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "prompt_version": self.prompt_version,
            "wall_clock_ms": round(self.wall_clock_ms, 2),
        }
