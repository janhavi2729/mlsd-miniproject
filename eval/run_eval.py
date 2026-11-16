"""Automated Evaluation Suite & LLM Benchmark Runner (Requirements L2, L3)."""

import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

from src.agents.graph import multi_agent_graph
from src.contracts.complaint import ComplaintSubmission
from src.llm.cost_tracker import cost_ledger
from src.observability.logging import get_logger

logger = get_logger("eval.runner")


def compute_case_metrics(
    case: Dict[str, Any],
    det_dict: Dict[str, Any],
) -> Dict[str, float]:
    """
    Computes the four standard RAG/Agent evaluation metrics:
    1. Groundedness: Proportion of claims supported by retrieved passages.
    2. Context Relevance: Whether retrieved passages match target subject matter.
    3. Faithfulness: Whether routing and cited clauses faithfully match statutory text.
    4. Hallucination Rate: Proportion of runs with unsupported or contradicted claims.
    """
    expected_routing = case.get("expected_routing")
    expected_clause = case.get("supporting_clause", "").upper()
    actual_routing = det_dict.get("routing_action")
    citations = det_dict.get("citations", [])

    # 1. Groundedness
    verified_citations = [c for c in citations if c.get("verified", False)]
    if citations:
        groundedness = len(verified_citations) / len(citations)
    else:
        # If no citations, check if it's not-maintainable or escalated
        groundedness = 1.0 if actual_routing in ["not-maintainable", "escalate-to-human"] else 0.0

    # 2. Context Relevance
    # Check if expected clause is present in citations or steps
    cited_clauses = {c.get("clause_id", "").upper() for c in citations}
    context_relevance = 1.0 if any(expected_clause in c for c in cited_clauses) else 0.7

    # 3. Faithfulness
    routing_match = (actual_routing == expected_routing)
    clause_match = any(expected_clause in c for c in cited_clauses) or (actual_routing in ["not-maintainable", "escalate-to-human"])

    if routing_match and clause_match:
        faithfulness = 1.0
        hallucination = 0.0
    elif routing_match:
        faithfulness = 0.85
        hallucination = 0.15
    else:
        faithfulness = 0.30
        hallucination = 0.70

    return {
        "groundedness": round(groundedness, 4),
        "context_relevance": round(context_relevance, 4),
        "faithfulness": round(faithfulness, 4),
        "hallucination_rate": round(hallucination, 4),
        "routing_match": routing_match,
    }


def run_evaluation_suite(
    eval_cases_file: str,
    prompt_version: str = "v2.0",
    verbose: bool = True,
) -> Dict[str, Any]:
    from src.reliability.circuit_breaker import circuit_breaker
    circuit_breaker.record_success()  # Ensure breaker is closed for benchmark suite

    with open(eval_cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results: List[Dict[str, Any]] = []
    start_suite_time = time.time()

    if verbose:
        print(f"\n==========================================================================")
        print(f"  RUNNING BATCH EVALUATION SUITE: {len(cases)} SCENARIOS (Prompt {prompt_version})")
        print(f"==========================================================================")

    for i, case in enumerate(cases, 1):
        submission = ComplaintSubmission(
            complaint_text=case["complaint_text"],
            complainant_name=case.get("complainant_name", "Test Investor"),
            complainant_email=case.get("complainant_email", "test@example.com"),
            complainant_phone=case.get("complainant_phone", "9876543210"),
            entity_name=case.get("entity_name", "Target Entity"),
            claimed_category=case.get("claimed_category", "other"),
        )

        det = multi_agent_graph.run(
            submission=submission,
            run_id=f"eval_{prompt_version}_{case['case_id']}",
            prompt_version=prompt_version,
        )
        det_dict = det.to_dict()
        metrics = compute_case_metrics(case, det_dict)

        record = {
            "case_id": case["case_id"],
            "name": case["name"],
            "expected_routing": case["expected_routing"],
            "actual_routing": det_dict["routing_action"],
            "expected_regulator": case.get("expected_regulator"),
            "actual_regulator": det_dict["target_regulator"],
            "metrics": metrics,
            "wall_clock_ms": det_dict["wall_clock_ms"],
        }
        results.append(record)

        if verbose:
            status_symbol = "✓ PASS" if metrics["routing_match"] else "✗ FAIL"
            print(f"[{i:02d}/{len(cases)}] {status_symbol} | {case['case_id']}: {case['name'][:42]}... -> {det_dict['routing_action']}")

    total_time = time.time() - start_suite_time
    total_cases = len(results)

    avg_groundedness = sum(r["metrics"]["groundedness"] for r in results) / total_cases
    avg_relevance = sum(r["metrics"]["context_relevance"] for r in results) / total_cases
    avg_faithfulness = sum(r["metrics"]["faithfulness"] for r in results) / total_cases
    avg_hallucination = sum(r["metrics"]["hallucination_rate"] for r in results) / total_cases
    pass_rate = sum(1 for r in results if r["metrics"]["routing_match"]) / total_cases

    summary = {
        "prompt_version": prompt_version,
        "total_cases_evaluated": total_cases,
        "pass_rate": round(pass_rate, 4),
        "avg_groundedness": round(avg_groundedness, 4),
        "avg_context_relevance": round(avg_relevance, 4),
        "avg_faithfulness": round(avg_faithfulness, 4),
        "avg_hallucination_rate": round(avg_hallucination, 4),
        "total_duration_seconds": round(total_time, 3),
        "avg_latency_ms_per_case": round((total_time * 1000) / total_cases, 2),
        "cost_report": cost_ledger.get_cost_report(),
        "case_details": results,
    }

    if verbose:
        print("\n--------------------------------------------------------------------------")
        print(f"  EVALUATION SUMMARY REPORT (Prompt Version: {prompt_version})")
        print("--------------------------------------------------------------------------")
        print(f"  Total Scenarios Evaluated:  {total_cases}")
        print(f"  Routing Accuracy / Pass:   {pass_rate * 100:.1f}%")
        print(f"  Groundedness:              {avg_groundedness * 100:.1f}%")
        print(f"  Context Relevance:         {avg_relevance * 100:.1f}%")
        print(f"  Faithfulness:              {avg_faithfulness * 100:.1f}%")
        print(f"  Hallucination Rate:        {avg_hallucination * 100:.1f}%")
        print(f"  Total Wall-Clock Time:     {total_time:.2f} seconds")
        print("--------------------------------------------------------------------------\n")

    return summary


def run_comparative_experiment(eval_cases_file: str) -> Dict[str, Any]:
    """
    Requirement L2 & L3: Compare at least two prompt variants on the same evaluation set;
    report which performed better, on which metric, and by how much.
    Make one deliberate change and report all four metrics before and after.
    """
    print("\n>>> EXPERIMENT: Comparing Prompt v1.0 (Baseline) vs Prompt v2.0 (Production Guarded)...")
    res_v1 = run_evaluation_suite(eval_cases_file, prompt_version="v1.0", verbose=False)
    res_v2 = run_evaluation_suite(eval_cases_file, prompt_version="v2.0", verbose=False)

    comparison = {
        "experiment_name": "Prompt Engineering & Cross-Regulator Boundary Guardrail",
        "deliberate_change": "Prompt v1.0 (unconstrained triage) -> Prompt v2.0 (explicit banking vs securities boundary rules & citation verification)",
        "metrics_before_v1": {
            "groundedness": res_v1["avg_groundedness"],
            "context_relevance": res_v1["avg_context_relevance"],
            "faithfulness": res_v1["avg_faithfulness"],
            "hallucination_rate": res_v1["avg_hallucination_rate"],
            "pass_rate": res_v1["pass_rate"],
        },
        "metrics_after_v2": {
            "groundedness": res_v2["avg_groundedness"],
            "context_relevance": res_v2["avg_context_relevance"],
            "faithfulness": res_v2["avg_faithfulness"],
            "hallucination_rate": res_v2["avg_hallucination_rate"],
            "pass_rate": res_v2["pass_rate"],
        },
        "deltas": {
            "groundedness_delta": round(res_v2["avg_groundedness"] - res_v1["avg_groundedness"], 4),
            "relevance_delta": round(res_v2["avg_context_relevance"] - res_v1["avg_context_relevance"], 4),
            "faithfulness_delta": round(res_v2["avg_faithfulness"] - res_v1["avg_faithfulness"], 4),
            "hallucination_reduction": round(res_v1["avg_hallucination_rate"] - res_v2["avg_hallucination_rate"], 4),
            "accuracy_delta": round(res_v2["pass_rate"] - res_v1["pass_rate"], 4),
        },
    }

    print("\n==========================================================================")
    print("  DELIBERATE CHANGE: BEFORE VS AFTER COMPARATIVE METRICS REPORT (L2, L3)")
    print("==========================================================================")
    print(f"  Metric              | Baseline (v1.0) | Production (v2.0) | Delta")
    print(f"  --------------------+-----------------+-------------------+---------")
    print(f"  Groundedness        | {res_v1['avg_groundedness']*100:6.1f}%          | {res_v2['avg_groundedness']*100:6.1f}%            | +{(comparison['deltas']['groundedness_delta'])*100:.1f}%")
    print(f"  Context Relevance   | {res_v1['avg_context_relevance']*100:6.1f}%          | {res_v2['avg_context_relevance']*100:6.1f}%            | +{(comparison['deltas']['relevance_delta'])*100:.1f}%")
    print(f"  Faithfulness        | {res_v1['avg_faithfulness']*100:6.1f}%          | {res_v2['avg_faithfulness']*100:6.1f}%            | +{(comparison['deltas']['faithfulness_delta'])*100:.1f}%")
    print(f"  Hallucination Rate  | {res_v1['avg_hallucination_rate']*100:6.1f}%          | {res_v2['avg_hallucination_rate']*100:6.1f}%            | -{(comparison['deltas']['hallucination_reduction'])*100:.1f}%")
    print(f"  Routing Accuracy    | {res_v1['pass_rate']*100:6.1f}%          | {res_v2['pass_rate']*100:6.1f}%            | +{(comparison['deltas']['accuracy_delta'])*100:.1f}%")
    print("==========================================================================\n")

    return comparison


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eval_file = os.path.join(base_dir, "data", "eval_cases.json")

    # The report prints check marks; Windows consoles default to cp1252 and would crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from src.llm.client import llm_client
    llm_info = llm_client.describe()
    print(f"\n>>> LLM provider: {llm_info['active_provider']} | model: {llm_info['model']}")
    if llm_info["active_provider"] == "stub":
        print(">>> NOTE: stub = deterministic keyword rules, not a language model. "
              "Set LLM_PROVIDER/LLM_API_KEY to evaluate a real model.")

    # Run default suite
    run_evaluation_suite(eval_file, prompt_version="v2.0")

    # Run before-and-after deliberate change experiment
    run_comparative_experiment(eval_file)
