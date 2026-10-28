"""Quarantine store for rejected invalid complaints at the ingestion boundary (Requirement D1, F2)."""

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class QuarantineStore:
    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._records: List[Dict[str, Any]] = []

        if self.storage_path and os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self._records = json.load(f)
            except Exception:
                self._records = []

    def quarantine(
        self,
        raw_payload: Dict[str, Any],
        validation_errors: List[Dict[str, str]],
        correlation_id: str,
        client_ip: Optional[str] = None,
    ) -> str:
        """Stores a malformed request with its field-level errors and returns quarantine record ID."""
        with self._lock:
            record_id = f"quarantine_{len(self._records) + 1}_{int(datetime.utcnow().timestamp())}"
            record = {
                "quarantine_id": record_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "correlation_id": correlation_id,
                "client_ip": client_ip or "unknown",
                "field_errors": validation_errors,
                "rejected_payload": raw_payload,
                "status": "QUARANTINED",
            }
            self._records.append(record)
            self._persist()
            return record_id

    def list_records(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(self._records[-limit:]))

    def get_record(self, quarantine_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for rec in self._records:
                if rec["quarantine_id"] == quarantine_id:
                    return rec
            return None

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def _persist(self):
        if self.storage_path:
            try:
                os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(self._records, f, indent=2)
            except Exception:
                pass


# Global singleton instance
_quarantine_store = QuarantineStore()


def get_quarantine_store() -> QuarantineStore:
    return _quarantine_store
