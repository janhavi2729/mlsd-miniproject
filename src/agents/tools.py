"""Agent tool definitions with bounded execution and telemetry (Requirement A1)."""

import time
from typing import Any, Dict, List, Optional
from src.retrieval.indexer import vector_index
from src.contracts.complaint import ComplaintSubmission
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("agents.tools")


class AgentToolRegistry:
    """Provides at least three tools callable by agents with execution tracking (Requirement A1)."""

    def __init__(self, submission: ComplaintSubmission, run_id: str):
        self.submission = submission
        self.run_id = run_id
        self.tool_call_count = 0
        self.tool_history: List[Dict[str, Any]] = []

    def corpus_search(
        self,
        query: str,
        top_k: int = 4,
        regulator: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Tool 1: Semantic vector retrieval over the regulatory corpus."""
        start = time.time()
        self.tool_call_count += 1
        metrics_collector.inc_counter("agent_tool_calls_total", 1.0, {"tool": "corpus_search"})

        results = vector_index.search(query=query, top_k=top_k, regulator_filter=regulator)
        duration_ms = (time.time() - start) * 1000.0

        self.tool_history.append({
            "tool": "corpus_search",
            "args": {"query": query, "top_k": top_k, "regulator": regulator},
            "results_count": len(results),
            "duration_ms": round(duration_ms, 2),
        })
        return results

    def clause_lookup(self, clause_id: str) -> Optional[Dict[str, Any]]:
        """Tool 2: Direct lookup of a clause by identifier (e.g. 'SEBI-CIR-03', 'RBI-IOS-08A')."""
        start = time.time()
        self.tool_call_count += 1
        metrics_collector.inc_counter("agent_tool_calls_total", 1.0, {"tool": "clause_lookup"})

        result = vector_index.lookup_by_clause(clause_id)
        duration_ms = (time.time() - start) * 1000.0

        self.tool_history.append({
            "tool": "clause_lookup",
            "args": {"clause_id": clause_id},
            "found": result is not None,
            "duration_ms": round(duration_ms, 2),
        })
        return result

    def request_field_lookup(self, field_name: str) -> Any:
        """Tool 3: Lookup of caller request's own fields (e.g. 'claimed_category', 'transaction_amount')."""
        start = time.time()
        self.tool_call_count += 1
        metrics_collector.inc_counter("agent_tool_calls_total", 1.0, {"tool": "request_field_lookup"})

        sub_dict = self.submission.to_dict()
        val = sub_dict.get(field_name.strip().lower(), None)
        duration_ms = (time.time() - start) * 1000.0

        self.tool_history.append({
            "tool": "request_field_lookup",
            "args": {"field_name": field_name},
            "value": str(val)[:100],
            "duration_ms": round(duration_ms, 2),
        })
        return val
