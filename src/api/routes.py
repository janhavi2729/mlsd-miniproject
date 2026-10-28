"""REST API routes and request dispatchers (Requirements F1, F2, F8, L6, D1, D5, D7)."""

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.contracts.complaint import ComplaintSubmission, validate_complaint
from src.contracts.determination import RoutingDetermination
from src.llm.stub_provider import stub_llm
from src.observability.logging import get_logger, set_request_context
from src.observability.metrics import metrics_collector
from src.observability.tracing import run_reconstruction_store
from src.queue.task_runner import TaskState, task_runner
from src.quarantine.store import get_quarantine_store
from src.reliability.circuit_breaker import circuit_breaker
from src.retrieval.cache import global_cache
from src.retrieval.indexer import vector_index

logger = get_logger("api.routes")
quarantine_store = get_quarantine_store()

# In-memory store for user feedback (Requirement L6)
FEEDBACK_STORE: List[Dict[str, Any]] = []


def handle_post_complaint(
    payload: Dict[str, Any],
    client_ip: str = "127.0.0.1",
    correlation_id: Optional[str] = None,
    prompt_version: str = "v2.0",
) -> Tuple[int, Dict[str, Any]]:
    """
    POST /api/v1/complaints
    Requirement F1, F2, D1: Enforces ingestion boundary validation. Quarantines rejects.
    Returns (status_code, response_dict).
    """
    corr_id = correlation_id or payload.get("correlation_id") or f"corr_{uuid.uuid4().hex[:8]}"
    set_request_context(correlation_id=corr_id)

    submission = ComplaintSubmission.from_dict(payload)
    submission.correlation_id = corr_id

    # Ingestion boundary validation (Requirement F2, D1)
    is_valid, errors = validate_complaint(submission)
    if not is_valid:
        # Quarantine malformed request with field-level errors
        q_id = quarantine_store.quarantine(
            raw_payload=payload,
            validation_errors=errors,
            correlation_id=corr_id,
            client_ip=client_ip,
        )
        metrics_collector.inc_counter("quarantine_records_total", 1.0)
        logger.warning(
            f"Ingestion rejected malformed payload; quarantined as {q_id}",
            extra_fields={"quarantine_id": q_id, "errors_count": len(errors)},
        )
        return 422, {
            "status": "REJECTED_AT_INGESTION_BOUNDARY",
            "message": "Complaint failed schema, categorical, or range validation at ingestion boundary.",
            "quarantine_id": q_id,
            "field_errors": errors,
            "agent_run_started": False,
            "correlation_id": corr_id,
        }

    # Valid complaint: Place task onto queue (Requirement A4)
    run_id = task_runner.submit_complaint(
        submission=submission,
        correlation_id=corr_id,
        prompt_version=prompt_version,
    )
    logger.info(f"Complaint accepted and queued with run_id {run_id}", extra_fields={"run_id": run_id})

    return 202, {
        "status": "ACCEPTED",
        "message": "Complaint accepted for asynchronous multi-agent processing.",
        "run_id": run_id,
        "correlation_id": corr_id,
        "poll_endpoint": f"/api/v1/runs/{run_id}",
        "trace_endpoint": f"/api/v1/runs/{run_id}/trace",
        "agent_run_started": True,
    }


def handle_get_run_status(run_id: str) -> Tuple[int, Dict[str, Any]]:
    """GET /api/v1/runs/{run_id} - Polling endpoint (Requirement A4)."""
    task = task_runner.get_task_status(run_id)
    if not task:
        return 404, {"error": f"Run identifier '{run_id}' not found."}
    return 200, task


def handle_get_run_trace(run_id: str) -> Tuple[int, Dict[str, Any]]:
    """
    GET /api/v1/runs/{run_id}/trace
    Requirement D5: Full run reconstruction (all tool calls, queries, passages, prompt version, step latency, cost).
    """
    full_trace = run_reconstruction_store.get_run(run_id)
    if not full_trace:
        task = task_runner.get_task_status(run_id)
        if task and task.get("result"):
            return 200, task["result"]
        return 404, {"error": f"No telemetry trace recorded for run '{run_id}'."}
    return 200, full_trace


def handle_post_feedback(run_id: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """
    POST /api/v1/runs/{run_id}/feedback (Requirement L6)
    Persists feedback (satisfactory: bool, reason: str) and tracks quality.
    """
    satisfactory = bool(payload.get("satisfactory", True))
    reason = str(payload.get("reason", "")).strip()

    feedback_record = {
        "feedback_id": f"fb_{uuid.uuid4().hex[:8]}",
        "run_id": run_id,
        "timestamp": time.time(),
        "satisfactory": satisfactory,
        "reason": reason,
    }
    FEEDBACK_STORE.append(feedback_record)
    metrics_collector.inc_counter(
        "user_feedback_total",
        1.0,
        {"satisfactory": str(satisfactory).lower()},
    )
    return 201, {"message": "Feedback recorded successfully.", "feedback": feedback_record}


def handle_get_feedback_summary() -> Tuple[int, Dict[str, Any]]:
    """GET /api/v1/feedback/summary (Requirement L6)."""
    total = len(FEEDBACK_STORE)
    if total == 0:
        return 200, {"total_feedback": 0, "satisfaction_rate": 1.0, "records": []}

    satisfactory_count = sum(1 for fb in FEEDBACK_STORE if fb["satisfactory"])
    rate = satisfactory_count / total
    return 200, {
        "total_feedback": total,
        "satisfactory_count": satisfactory_count,
        "unsatisfactory_count": total - satisfactory_count,
        "satisfaction_rate": round(rate, 3),
        "recent_feedback": list(reversed(FEEDBACK_STORE[-20:])),
    }


def handle_get_quarantine(limit: int = 50) -> Tuple[int, Dict[str, Any]]:
    """GET /api/v1/quarantine (Requirement F2, D1)."""
    records = quarantine_store.list_records(limit=limit)
    return 200, {
        "total_quarantined": quarantine_store.count(),
        "limit": limit,
        "records": records,
    }


def handle_get_health() -> Tuple[int, Dict[str, Any]]:
    """GET /health - Service health and dependency checks (Requirement F8, D3)."""
    uptime = time.time() - metrics_collector.gauges.get("securities_service_uptime_seconds", time.time())
    cb_state = circuit_breaker.state.value
    chunks_count = len(vector_index.chunks)

    return 200, {
        "status": "HEALTHY",
        "service": "securities-investor-grievance-routing",
        "uptime_seconds": round(uptime, 1),
        "circuit_breaker": cb_state,
        "vector_index_chunks": chunks_count,
        "cache_stats": global_cache.get_cache_stats(),
        "quarantined_records": quarantine_store.count(),
    }


def handle_get_metrics() -> str:
    """GET /metrics - Prometheus plaintext exposition format (Requirement D5)."""
    return metrics_collector.generate_prometheus_text()


def handle_toggle_circuit_breaker(force_fail: bool, message: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    """POST /api/v1/admin/toggle-circuit-breaker (Hook for Demonstration Item 8)."""
    stub_llm.set_fail_mode(force_fail, message)
    if force_fail:
        # Simulate multiple failures to trip breaker
        for _ in range(circuit_breaker.failure_threshold):
            circuit_breaker.record_failure()
    else:
        circuit_breaker.record_success()

    return 200, {
        "simulated_provider_fail_mode": stub_llm.fail_mode,
        "circuit_breaker_state": circuit_breaker.state.value,
        "consecutive_failures": circuit_breaker.consecutive_failures,
    }
