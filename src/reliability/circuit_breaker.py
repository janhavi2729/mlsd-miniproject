"""Circuit Breaker pattern for provider resilience (Requirement A5)."""

import enum
import threading
import time
from typing import Callable, Any, Optional
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("reliability.circuit_breaker")


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(Exception):
    """Raised when the circuit breaker is OPEN to fail fast."""
    pass


class CircuitBreaker:
    def __init__(
        self,
        name: str = "llm_provider",
        failure_threshold: int = 4,
        recovery_timeout_seconds: float = 15.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds

        self._lock = threading.Lock()
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time: Optional[float] = None
        self._update_metrics()

    def _update_metrics(self):
        state_num = 0.0
        if self.state == CircuitState.HALF_OPEN:
            state_num = 1.0
        elif self.state == CircuitState.OPEN:
            state_num = 2.0
        metrics_collector.set_gauge("circuit_breaker_state", state_num, {"breaker": self.name})

    def record_success(self):
        with self._lock:
            if self.state != CircuitState.CLOSED:
                logger.info("Circuit breaker reset to CLOSED after successful probe", extra_fields={"breaker": self.name})
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self._update_metrics()

    def record_failure(self):
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_time = time.time()
            metrics_collector.inc_counter("circuit_breaker_failures_total", 1.0, {"breaker": self.name})

            if self.consecutive_failures >= self.failure_threshold and self.state != CircuitState.OPEN:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker tripped to OPEN! Consecutive failures: {self.consecutive_failures}",
                    extra_fields={"breaker": self.name, "failures": self.consecutive_failures},
                )
            self._update_metrics()

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                now = time.time()
                if self.last_failure_time and (now - self.last_failure_time >= self.recovery_timeout_seconds):
                    self.state = CircuitState.HALF_OPEN
                    logger.info("Circuit breaker transitioned to HALF_OPEN (probing provider)", extra_fields={"breaker": self.name})
                    self._update_metrics()
                    return True
                return False
            if self.state == CircuitState.HALF_OPEN:
                return True
            return False

    def execute(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        if not self.can_execute():
            raise CircuitBreakerOpenException(
                f"Circuit breaker '{self.name}' is OPEN. Provider unavailable; failing fast."
            )
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise e


circuit_breaker = CircuitBreaker()
