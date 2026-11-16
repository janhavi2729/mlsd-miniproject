"""Token and Cost Accounting (Requirement L5)."""

import threading
from typing import Any, Dict, List, Optional
from src.config import settings
from src.contracts.determination import TokenUsage


# Cost rates come from config (LLM_COST_PER_1M_INPUT / LLM_COST_PER_1M_OUTPUT).
# Defaults: $0.15 / $0.60 per 1M tokens (GPT-4o-mini-class pricing).
COST_PER_PROMPT_TOKEN = settings.LLM_COST_PER_1M_INPUT / 1_000_000
COST_PER_COMPLETION_TOKEN = settings.LLM_COST_PER_1M_OUTPUT / 1_000_000


class CostAccountingLedger:
    def __init__(self):
        self._lock = threading.Lock()
        self.step_costs: List[Dict[str, Any]] = []
        self.run_costs: List[Dict[str, Any]] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_usd: float = 0.0

    def record_call(
        self,
        run_id: str,
        step_name: str,
        agent_name: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> TokenUsage:
        prompt_cost = prompt_tokens * COST_PER_PROMPT_TOKEN
        comp_cost = completion_tokens * COST_PER_COMPLETION_TOKEN
        call_cost = prompt_cost + comp_cost

        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=call_cost,
        )

        with self._lock:
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_cost_usd += call_cost

            self.step_costs.append({
                "run_id": run_id,
                "step_name": step_name,
                "agent_name": agent_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": call_cost,
            })

        return usage

    def get_cost_report(self) -> Dict[str, Any]:
        with self._lock:
            runs_count = len({s["run_id"] for s in self.step_costs})
            runs_denom = max(runs_count, 1)
            cost_per_run = self.total_cost_usd / runs_denom
            cost_per_100_runs = cost_per_run * 100

            # Determine largest single cost driver by step/agent
            driver_costs: Dict[str, float] = {}
            for item in self.step_costs:
                key = f"{item['agent_name']}::{item['step_name']}"
                driver_costs[key] = driver_costs.get(key, 0.0) + item["cost_usd"]

            largest_driver = "none"
            largest_driver_cost = 0.0
            if driver_costs:
                largest_driver = max(driver_costs, key=driver_costs.get)
                largest_driver_cost = driver_costs[largest_driver]

            return {
                "total_runs_recorded": runs_count,
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_cost_usd": round(self.total_cost_usd, 6),
                "cost_per_run_usd": round(cost_per_run, 6),
                "cost_per_100_runs_usd": round(cost_per_100_runs, 4),
                "largest_single_cost_driver": largest_driver,
                "largest_driver_cost_usd": round(largest_driver_cost, 6),
                "driver_breakdown": {k: round(v, 6) for k, v in driver_costs.items()},
            }


cost_ledger = CostAccountingLedger()
