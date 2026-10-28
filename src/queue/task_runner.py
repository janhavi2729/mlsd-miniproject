"""Asynchronous Task Runner and Queue Execution Engine (Requirement A4)."""

import concurrent.futures
import enum
import threading
import time
import uuid
from typing import Any, Dict, Optional

from src.agents.graph import multi_agent_graph
from src.contracts.complaint import ComplaintSubmission
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("queue.task_runner")


class TaskState(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


class AsyncTaskRunner:
    """
    Task runner placing a queue between ingestion submission and agent execution.
    Returns run_id immediately, executes asynchronously, allows polling of status.
    """

    def __init__(self, max_workers: int = 4):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def submit_complaint(
        self,
        submission: ComplaintSubmission,
        correlation_id: Optional[str] = None,
        prompt_version: str = "v2.0",
    ) -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        corr_id = correlation_id or submission.correlation_id or f"corr_{uuid.uuid4().hex[:8]}"

        with self._lock:
            self._tasks[run_id] = {
                "run_id": run_id,
                "correlation_id": corr_id,
                "status": TaskState.QUEUED.value,
                "submitted_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "prompt_version": prompt_version,
            }

        metrics_collector.inc_counter("queue_tasks_submitted_total", 1.0)
        self.executor.submit(self._worker_execute, run_id, submission, corr_id, prompt_version)
        return run_id

    def _worker_execute(
        self,
        run_id: str,
        submission: ComplaintSubmission,
        correlation_id: str,
        prompt_version: str,
    ):
        with self._lock:
            if run_id in self._tasks:
                self._tasks[run_id]["status"] = TaskState.RUNNING.value
                self._tasks[run_id]["started_at"] = time.time()

        try:
            determination = multi_agent_graph.run(
                submission=submission,
                run_id=run_id,
                correlation_id=correlation_id,
                prompt_version=prompt_version,
            )
            det_dict = determination.to_dict()

            with self._lock:
                if run_id in self._tasks:
                    final_status = (
                        TaskState.ESCALATED.value
                        if determination.requires_human_escalation
                        else TaskState.COMPLETED.value
                    )
                    self._tasks[run_id]["status"] = final_status
                    self._tasks[run_id]["finished_at"] = time.time()
                    self._tasks[run_id]["result"] = det_dict

        except Exception as e:
            logger.error(f"Worker task error for run {run_id}: {e}", extra_fields={"run_id": run_id})
            with self._lock:
                if run_id in self._tasks:
                    self._tasks[run_id]["status"] = TaskState.FAILED.value
                    self._tasks[run_id]["finished_at"] = time.time()
                    self._tasks[run_id]["error"] = str(e)

    def get_task_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(run_id)
            if not task:
                return None
            copied = dict(task)
            # Calculate elapsed time
            now = time.time()
            if copied["status"] in [TaskState.QUEUED.value, TaskState.RUNNING.value]:
                copied["elapsed_seconds"] = round(now - copied["submitted_at"], 2)
            elif copied["finished_at"]:
                copied["elapsed_seconds"] = round(copied["finished_at"] - copied["submitted_at"], 2)
            return copied

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._tasks.values())
            return list(reversed(items[-limit:]))


task_runner = AsyncTaskRunner()
