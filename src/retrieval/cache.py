"""Multi-level Cache: exact queries, vector retrieval, and whole run determinations (Requirement D7)."""

import hashlib
import json
import threading
import time
from typing import Any, Dict, Optional, Tuple
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("retrieval.cache")


class TieredCache:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._query_cache: Dict[str, Tuple[float, Any]] = {}
        self._run_cache: Dict[str, Tuple[float, Any]] = {}

        self.hits_query: int = 0
        self.misses_query: int = 0
        self.hits_run: int = 0
        self.misses_run: int = 0

    def _hash_key(self, key_text: str) -> str:
        return hashlib.sha256(key_text.strip().lower().encode("utf-8")).hexdigest()

    def get_query(self, query: str) -> Optional[Any]:
        key = self._hash_key(query)
        with self._lock:
            if key in self._query_cache:
                timestamp, data = self._query_cache[key]
                if time.time() - timestamp < self.ttl_seconds:
                    self.hits_query += 1
                    metrics_collector.inc_counter("cache_hits_total", 1.0, {"tier": "query"})
                    return data
                else:
                    del self._query_cache[key]
            self.misses_query += 1
            metrics_collector.inc_counter("cache_misses_total", 1.0, {"tier": "query"})
            return None

    def set_query(self, query: str, data: Any):
        key = self._hash_key(query)
        with self._lock:
            self._query_cache[key] = (time.time(), data)

    def get_run(self, complaint_text: str, entity_name: str) -> Optional[Any]:
        raw = f"{complaint_text}|{entity_name}"
        key = self._hash_key(raw)
        with self._lock:
            if key in self._run_cache:
                timestamp, data = self._run_cache[key]
                if time.time() - timestamp < self.ttl_seconds:
                    self.hits_run += 1
                    metrics_collector.inc_counter("cache_hits_total", 1.0, {"tier": "run"})
                    return data
                else:
                    del self._run_cache[key]
            self.misses_run += 1
            metrics_collector.inc_counter("cache_misses_total", 1.0, {"tier": "run"})
            return None

    def set_run(self, complaint_text: str, entity_name: str, determination_dict: Dict[str, Any]):
        raw = f"{complaint_text}|{entity_name}"
        key = self._hash_key(raw)
        with self._lock:
            self._run_cache[key] = (time.time(), determination_dict)

    def get_cache_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_q = self.hits_query + self.misses_query
            q_hit_rate = (self.hits_query / total_q) if total_q > 0 else 0.0

            total_r = self.hits_run + self.misses_run
            r_hit_rate = (self.hits_run / total_r) if total_r > 0 else 0.0

            return {
                "query_cache_entries": len(self._query_cache),
                "query_hits": self.hits_query,
                "query_misses": self.misses_query,
                "query_hit_rate": round(q_hit_rate, 3),
                "run_cache_entries": len(self._run_cache),
                "run_hits": self.hits_run,
                "run_misses": self.misses_run,
                "run_hit_rate": round(r_hit_rate, 3),
            }


global_cache = TieredCache()
