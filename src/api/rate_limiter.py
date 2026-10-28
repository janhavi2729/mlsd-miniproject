"""Per-client token bucket rate limiter (Requirement D7: Rate Limiting & Cost Control)."""

import threading
import time
from typing import Dict, Tuple
from src.observability.metrics import metrics_collector


class TokenBucketRateLimiter:
    """
    Token bucket algorithm to protect agent endpoints from looping clients.
    One client looping against a multi-step agent can exhaust the budget in minutes.
    """

    def __init__(self, rate: float = 15.0, capacity: int = 30):
        self.rate = rate  # tokens added per second
        self.capacity = capacity  # max bucket burst capacity
        self._lock = threading.Lock()
        self.buckets: Dict[str, Tuple[float, float]] = {}  # client_id -> (tokens, last_time)

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        with self._lock:
            tokens, last_time = self.buckets.get(client_id, (self.capacity, now))
            # Replenish tokens
            elapsed = now - last_time
            tokens = min(self.capacity, tokens + elapsed * self.rate)

            if tokens >= 1.0:
                self.buckets[client_id] = (tokens - 1.0, now)
                return True
            else:
                self.buckets[client_id] = (tokens, now)
                metrics_collector.inc_counter("rate_limit_exceeded_total", 1.0, {"client": client_id})
                return False


rate_limiter = TokenBucketRateLimiter()
