"""Bounded exponential backoff retry mechanism (Requirement A5)."""

import random
import time
from typing import Any, Callable
from src.observability.logging import get_logger
from src.observability.metrics import metrics_collector

logger = get_logger("reliability.retry")


def execute_with_retry(
    func: Callable[..., Any],
    max_retries: int = 3,
    base_delay_seconds: float = 0.2,
    max_delay_seconds: float = 2.0,
    retry_exceptions: tuple = (ConnectionError, TimeoutError),
    step_name: str = "generic_step",
    *args,
    **kwargs,
) -> Any:
    """Executes a callable with bounded exponential backoff and jitter."""
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
        except retry_exceptions as exc:
            attempt += 1
            metrics_collector.inc_counter("agent_retries_total", 1.0, {"step": step_name})
            if attempt > max_retries:
                logger.error(
                    f"Max retry limit ({max_retries}) exceeded for {step_name}: {exc}",
                    extra_fields={"step": step_name, "attempts": attempt},
                )
                raise exc

            backoff = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            jitter = random.uniform(0.0, 0.1 * backoff)
            sleep_time = backoff + jitter

            logger.warning(
                f"Attempt {attempt}/{max_retries} failed for {step_name}. Retrying in {sleep_time:.3f}s: {exc}",
                extra_fields={"step": step_name, "attempt": attempt, "backoff_s": sleep_time},
            )
            time.sleep(sleep_time)
