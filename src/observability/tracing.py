"""OpenTelemetry & run execution reconstruction tracing (Requirement D5)."""

import json
import threading
import time
from typing import Any, Dict, List, Optional


class Span:
    def __init__(self, name: str, trace_id: str, span_id: str, parent_id: Optional[str] = None):
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.attributes: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def finish(self):
        self.end_time = time.time()

    def to_dict(self) -> Dict[str, Any]:
        duration_ms = ((self.end_time or time.time()) - self.start_time) * 1000.0
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "duration_ms": round(duration_ms, 2),
            "attributes": self.attributes,
            "events": self.events,
        }


class RunReconstructionStore:
    """Stores full telemetry and execution artifacts for full run reconstruction (Requirement D5)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._runs: Dict[str, Dict[str, Any]] = {}

    def save_run(self, run_id: str, full_record: Dict[str, Any]):
        with self._lock:
            self._runs[run_id] = full_record

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._runs.get(run_id)

    def list_recent_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            all_runs = list(self._runs.values())
            return list(reversed(all_runs[-limit:]))


run_reconstruction_store = RunReconstructionStore()
