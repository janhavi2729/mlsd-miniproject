"""Prometheus metrics exporter and collector (Requirement D5, F8, A6, D2)."""

import bisect
import threading
import time
from typing import Dict, List, Tuple


class MetricsCollector:
    """In-memory thread-safe metrics engine supporting Prometheus text exposition."""

    def __init__(self):
        self._lock = threading.Lock()
        self.counters: Dict[str, float] = {}
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, List[float]] = {}
        self.histogram_buckets = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 8.0, 10.0, 15.0, 30.0]

        # Initialize defaults
        self.gauges["securities_service_uptime_seconds"] = time.time()
        self.gauges["corpus_chunks_total"] = 0.0
        self.gauges["corpus_freshness_timestamp"] = time.time()
        self.gauges["circuit_breaker_state"] = 0.0  # 0=Closed, 1=Half-Open, 2=Open

    def inc_counter(self, name: str, value: float = 1.0, labels: Dict[str, str] = None):
        key = self._format_key(name, labels)
        with self._lock:
            self.counters[key] = self.counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        key = self._format_key(name, labels)
        with self._lock:
            self.gauges[key] = float(value)

    def observe_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        key = self._format_key(name, labels)
        with self._lock:
            if key not in self.histograms:
                self.histograms[key] = []
            self.histograms[key].append(float(value))

    def _format_key(self, name: str, labels: Dict[str, str] = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def get_summary_stats(self) -> Dict[str, float]:
        """Calculates p50, p95, throughput for dashboard display."""
        with self._lock:
            all_durations = []
            for k, vals in self.histograms.items():
                if "agent_run_duration_seconds" in k:
                    all_durations.extend(vals)

            if not all_durations:
                return {"p50": 0.0, "p95": 0.0, "count": 0, "avg": 0.0}

            s = sorted(all_durations)
            n = len(s)
            p50 = s[int(0.50 * n)]
            p95 = s[min(int(0.95 * n), n - 1)]
            avg = sum(s) / n
            return {"p50": round(p50, 3), "p95": round(p95, 3), "count": n, "avg": round(avg, 3)}

    def generate_prometheus_text(self) -> str:
        """Renders metrics in official Prometheus plaintext exposition format."""
        lines = []
        with self._lock:
            # Counters
            for key, val in sorted(self.counters.items()):
                base_name = key.split("{")[0]
                lines.append(f"# TYPE {base_name} counter")
                lines.append(f"{key} {val}")

            # Gauges
            for key, val in sorted(self.gauges.items()):
                base_name = key.split("{")[0]
                lines.append(f"# TYPE {base_name} gauge")
                lines.append(f"{key} {val}")

            # Histograms
            for key, values in sorted(self.histograms.items()):
                base_name = key.split("{")[0]
                labels_part = ""
                if "{" in key:
                    labels_part = key[key.index("{") + 1 : -1]

                lines.append(f"# TYPE {base_name} histogram")
                s_vals = sorted(values)
                count = len(s_vals)
                total_sum = sum(s_vals)

                for b in self.histogram_buckets:
                    idx = bisect.bisect_right(s_vals, b)
                    bucket_labels = f'le="{b}"' if not labels_part else f'{labels_part},le="{b}"'
                    lines.append(f"{base_name}_bucket{{{bucket_labels}}} {idx}")

                inf_labels = 'le="+Inf"' if not labels_part else f'{labels_part},le="+Inf"'
                lines.append(f"{base_name}_bucket{{{inf_labels}}} {count}")
                lines.append(f"{base_name}_count{{{labels_part}}} {count}")
                lines.append(f"{base_name}_sum{{{labels_part}}} {round(total_sum, 4)}")

        return "\n".join(lines) + "\n"


metrics_collector = MetricsCollector()
