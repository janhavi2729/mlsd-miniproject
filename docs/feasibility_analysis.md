# Feasibility Analysis — Securities Investor Grievance Routing Service
**Team:** Janhavi Rajpurohit (PES1UG24AM121) · Kasissnu SSinha (PES1UG24AM130)

---

## 1. Technical Feasibility

### 1.1 Core System Components
| Component | Technology | Status |
|---|---|---|
| Multi-Agent Reasoning | Python stdlib (no GPU, no API key needed) | ✅ Working |
| Regulatory Corpus Retrieval | TF-IDF + cosine similarity (offline, zero-dependency) | ✅ Working |
| REST API | Python `http.server` (stdlib) or FastAPI | ✅ Working |
| Async Task Queue | Python `ThreadPoolExecutor` (embedded) | ✅ Working |
| Observability | Custom Prometheus-compatible metrics exporter | ✅ Working |
| Circuit Breaker | Custom token-bucket state machine | ✅ Working |
| Web UI | Vanilla HTML/CSS/JS (no framework) | ✅ Working |

### 1.2 Zero External Dependency Operation
The system is designed to run **without any internet connection, API key, or paid service**:
- LLM calls are served by a deterministic `StubLLMProvider` (replaceable with Gemini/OpenAI via env var `LLM_PROVIDER=gemini`)
- Embeddings are computed locally using TF-IDF (no `sentence-transformers`, no OpenAI embeddings)
- Queue uses in-process `ThreadPoolExecutor` (no Redis needed in dev mode; Redis available for production via docker compose)
- All dependencies in `requirements.txt` are optional accelerators — the stdlib server runs with zero pip installs

### 1.3 Regulatory Corpus Coverage
| Document | Clauses Indexed | Status |
|---|---|---|
| SEBI Master Circular — SCORES 2.0 | 6 clauses, 11 chunks | ✅ |
| SEBI (Mutual Funds) Regulations 1996 | 5 regulations, 10 chunks | ✅ |
| RBI Integrated Ombudsman Scheme 2021 | 5 clauses, 13 chunks | ✅ |
| Cross-Regulatory Jurisdiction Guide | 4 clauses, 8 chunks | ✅ |
| **Total** | **42 chunks, 869-dimensional vocabulary** | ✅ |

### 1.4 Accuracy Benchmarks (Evaluated against 21 labelled test cases)
| Metric | Result |
|---|---|
| Routing Accuracy (correct jurisdiction decision) | **100%** |
| Citation Groundedness (verified against retrieved text) | **100%** |
| Faithfulness (SLA and clause correct) | **97.1%** |
| Hallucination Rate | **2.9%** |

---

## 2. Operational Feasibility

### 2.1 Service Level Objectives — Load Test Results
**Declared SLO:** p95 latency ≤ 4.0 seconds end-to-end (submission → final routing determination)

| Concurrency | Throughput (RPS) | p50 latency | p95 latency | SLO |
|---|---|---|---|---|
| 1 | ~12 | 0.083s | 0.085s | ✅ MET |
| 4 | 22.9 | 0.165s | 0.193s | ✅ MET |
| 8 | ~22 | 0.38s | 0.42s | ✅ MET |
| 16 | ~23 | 0.75s | 0.82s | ✅ MET |
| 32 | 24.1 | 1.29s | **1.34s** | ✅ MET |

**Conclusion:** The system comfortably meets the declared SLO at all tested concurrency levels. The SLO would only be stressed when an actual external LLM API is called (typically 1–3s per call). Horizontal scaling via `docker compose up --scale agent-worker=N` handles increased load.

### 2.2 Bottleneck Identification & Mitigation Plan
| Bottleneck | Where | Mitigation |
|---|---|---|
| LLM API latency (real provider) | `src/llm/client.py` | Circuit breaker + retry + graceful fallback path |
| Vector search at very large corpus scale | `src/retrieval/indexer.py` | Replace TF-IDF with FAISS or ChromaDB (drop-in) |
| Python GIL under very high concurrency | Task runner thread pool | Switch to `asyncio` + `uvicorn` workers (FastAPI path) |
| Redis unavailability | Queue broker | `USE_EMBEDDED_QUEUE=true` fallback (in-process) |

### 2.3 Deployment Feasibility
- **Local dev:** `python -m src.api.main` — runs in < 2 seconds, zero configuration
- **Containerised production:** `docker compose up` — 6 services, all health-checked
- **Cloud (any provider):** Docker-compatible; env vars in `.env.example` map directly to any cloud secret manager

---

## 3. Financial Feasibility

### 3.1 Token Cost Analysis (per LLM call — production pricing)
| Step | Prompt Tokens | Completion Tokens | Cost per run (at \$0.15/1M prompt, \$0.60/1M completion) |
|---|---|---|---|
| TriageAgent classification | ~320 | ~110 | \$0.000114 |
| RoutingAgent adjudication | ~460 | ~150 | \$0.000159 |
| **Total per complaint** | **~780** | **~260** | **\$0.000273** |

**100,000 complaints/month → \$27.30/month in LLM tokens**

This is economically trivial compared to the cost of manual grievance routing (estimated 5–10 minutes per officer, at ₹30,000/month salary = ~₹2–4 per complaint manually).

### 3.2 Infrastructure Cost (cloud hosting estimate)
| Component | Instance Type | Monthly Cost |
|---|---|---|
| API + Agent Worker | 2× t3.small (AWS) | ~\$15/month |
| Redis | ElastiCache t3.micro | ~\$12/month |
| Prometheus + Grafana | t3.micro | ~\$6/month |
| **Total** | | **~\$33/month** |

---

## 4. Legal / Regulatory Feasibility

- The system produces **routing recommendations**, not legally binding orders — all determinations carry a human review escalation path
- All cited clauses reference publicly available SEBI Master Circulars and RBI Integrated Ombudsman Scheme — no proprietary data
- Split-jurisdiction cases are **mandatorily escalated to human** (Requirement F7 / CROSS-REG-04) — the system cannot autonomously adjudicate multi-regulator disputes
- Output filter blocks any text resembling a judicial award, guaranteed settlement, or trading recommendation
- Prompt injection guardrail prevents adversarial manipulation of the routing engine

---

## 5. Conclusion

The system is **technically, operationally, financially, and legally feasible** for production deployment as an assistive first-tier triage tool for SEBI's SCORES 2.0 investor grievance portal.
