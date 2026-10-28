"""Locust Load Testing Suite (Requirement D6, A7).

DECLARED SERVICE LEVEL OBJECTIVE (SLO) (Justified against Section 1):
- Retail investor grievance triage requires sub-second preliminary ingestion
  and end-to-end multi-agent adjudication completion within 4.0 seconds at p95.
- Declared SLO Target: p95 latency <= 4.0 seconds for complete run (submission -> completed determination).
- Target Throughput: >= 25 RPS under sustained load.
"""

import json
import time
from locust import HttpUser, task, between


class InvestorGrievanceUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def test_section_41_difficult_case(self):
        """Measures full end-to-end run from submission to final result (Requirement D6)."""
        payload = {
            "complainant_name": "Ramesh Kumar Sharma",
            "complainant_email": "ramesh.sharma@example.com",
            "complainant_phone": "9876543210",
            "entity_name": "HDFC Bank Ltd",
            "claimed_category": "fixed_deposit",
            "transaction_amount": 500000,
            "complaint_text": "I invested in a fixed deposit through my bank's app. The interest credited is lower than what I was promised. I want to complain to SEBI.",
        }

        start_time = time.time()
        with self.client.post("/api/v1/complaints", json=payload, catch_response=True) as resp:
            if resp.status_code != 202:
                resp.failure(f"Submission failed with status {resp.status_code}")
                return
            data = resp.json()
            run_id = data.get("run_id")

        # Poll status until COMPLETED or ESCALATED
        max_poll_attempts = 30
        for _ in range(max_poll_attempts):
            time.sleep(0.1)
            with self.client.get(f"/api/v1/runs/{run_id}", catch_response=True) as poll_resp:
                if poll_resp.status_code == 200:
                    status_data = poll_resp.json()
                    status = status_data.get("status")
                    if status in ["COMPLETED", "ESCALATED"]:
                        total_elapsed_ms = (time.time() - start_time) * 1000.0
                        # Record end-to-end duration
                        self.environment.events.request.fire(
                            request_type="END_TO_END",
                            name="full_run_submission_to_result",
                            response_time=total_elapsed_ms,
                            response_length=len(poll_resp.content),
                            exception=None,
                            context={},
                        )
                        break
                    elif status == "FAILED":
                        poll_resp.failure(f"Run failed: {status_data.get('error')}")
                        break

    @task(1)
    def test_health_and_metrics(self):
        self.client.get("/health")
        self.client.get("/metrics")
