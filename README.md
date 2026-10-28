# Securities Investor Grievance Routing Service
### Multi-Agent Regulatory Triage, Jurisdiction Mapping & Statutory Routing
**Course:** UE24AM342AA5 — ML System Design & AgentOps  
**Team:** Janhavi Rajpurohit (PES1UG24AM121) · Kasissnu SSinha (PES1UG24AM130)

---

## Problem Statement

Retail investors filing grievances in India frequently misroute their complaints — particularly to **SEBI** (Securities and Exchange Board of India) for issues that actually fall under **RBI** (Reserve Bank of India), **IRDAI**, or **PFRDA**. The *Section 4.1 Difficult Case*: a bank Fixed Deposit dispute phrased with investment vocabulary ("I invested in an FD… I want to complain to SEBI") is the canonical failure mode.

This project implements a **multi-agent RAG system** that:
1. Reads a complaint in natural language
2. Identifies the **underlying financial instrument and operating entity**
3. Maps to **statutory jurisdiction** using a retrievable corpus of SEBI Master Circulars, RBI Integrated Ombudsman Scheme, and cross-regulatory guidelines
4. Routes to one of four deterministic outputs: `assign-to-entity` (SEBI SCORES 2.0), `refer-to-other-regulator` (RBI/IRDAI/PFRDA/MCA), `not-maintainable`, or `escalate-to-human` (split-jurisdiction)
5. Cites the exact statutory clause verifying the determination

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ REST API Ingestion Gateway (src/api/main.py)                    │
│  • Schema / categorical / range validation (F2, D1)             │
│  • Quarantine store for rejected payloads                        │
│  • Rate limiter (15 RPS token bucket)                            │
└───────────────────────┬─────────────────────────────────────────┘
                        │ 202 Accepted → Task Queue (A4)
┌───────────────────────▼─────────────────────────────────────────┐
│ Multi-Agent Reasoning Graph (src/agents/graph.py)               │
│                                                                  │
│  [Guardrail Screener] (prompt injection, toxicity, L4)          │
│           │                                                      │
│  [Agent 1: TriageAgent]   (Tool 1: corpus_search,               │
│      Jurisdictional        Tool 3: request_field_lookup)         │
│      Classification        LLM: v2.0 prompt with                │
│           │                     explicit banking boundary        │
│   Hand-off payload                                               │
│           │                                                      │
│  [Agent 2: RoutingAgent]  (Tool 2: clause_lookup,               │
│      Regulatory            Tool 1: corpus_search)               │
│      Adjudication          LLM: v2.0 adjudication prompt        │
│           │                                                      │
│  [Evidence Verifier]  Citation grounded against retrieved text  │
│  [Output Filter]      Block judicial/investment advice claims    │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│ Routing Determination (src/contracts/determination.py)          │
│  routing_action | target_regulator | citations (verified) |     │
│  resolution_timeline_days | requires_escalation | step traces   │
└─────────────────────────────────────────────────────────────────┘
```

### Services (Docker Compose — Requirement D3)
| Service | Port | Role |
|---|---|---|
| `api-service` | 8000 | REST gateway, ingestion, web UI |
| `agent-worker` | — | Async multi-agent runner (scalable with `--scale`) |
| `redis` | 6379 | Queue, cache, state store |
| `prometheus` | 9090 | Metrics scraper |
| `grafana` | 3000 | AgentOps dashboard |
| `jaeger` | 16686 | Distributed trace UI |

---

## Running the Service

### Zero-Dependency (Python only, no installs needed for stdlib server)
```bash
# 1. Clone and enter project
cd securities-grievance-routing

# 2. Set up virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 3. Build the corpus index
python -m src.retrieval.indexer

# 4. Start the standalone HTTP server (no package installs required)
python -m src.api.main
# → Service at http://localhost:8000
# → Web UI at http://localhost:8000
```

### With FastAPI (uvicorn, if packages available)
```bash
pip install fastapi uvicorn
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Compose (full stack)
```bash
docker compose up --build
# Scale workers:
docker compose up --scale agent-worker=3
```

---

## REST API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/complaints` | Submit grievance for multi-agent routing |
| `GET` | `/api/v1/runs/{run_id}` | Poll task status |
| `GET` | `/api/v1/runs/{run_id}/trace` | Full run reconstruction (D5) |
| `POST` | `/api/v1/runs/{run_id}/feedback` | Submit caller feedback (L6) |
| `GET` | `/api/v1/feedback/summary` | Feedback satisfaction summary |
| `GET` | `/api/v1/quarantine` | View rejected/quarantined payloads |
| `GET` | `/health` | Service health + dependency check |
| `GET` | `/metrics` | Prometheus plaintext metrics |
| `POST` | `/api/v1/admin/toggle-circuit-breaker` | Demo Item 8: trip/restore breaker |

---

## Running Tests

```bash
# Full unit + integration test suite (39 tests)
python -m unittest tests.test_suite -v

# Evaluation suite (21 scenarios × 2 prompt variants — L2, L3)
python -m eval.run_eval

# SLO Load Test Benchmark (D6, A7)
python tests/load_test_benchmark.py
```

### Evaluation Results (Prompt v1.0 Baseline → v2.0 Production)
| Metric | Baseline v1.0 | Production v2.0 | Delta |
|---|---|---|---|
| Routing Accuracy | 95.2% | **100.0%** | +4.8% |
| Faithfulness | 93.8% | **97.1%** | +3.3% |
| Hallucination Rate | 6.2% | **2.9%** | −3.3% |
| Context Relevance | 92.9% | **94.3%** | +1.4% |
| Groundedness | 100.0% | 100.0% | — |

**Deliberate change:** Added explicit cross-regulator banking-vs-securities boundary rule and mandatory split-jurisdiction escalation in Prompt v2.0.

### SLO Benchmark (D6)
- **Declared SLO:** p95 latency ≤ 4.0 seconds end-to-end
- **Achieved (Concurrency 4):** p50 = 0.165s, p95 = 0.193s — **SLO MET ✓**
- **Achieved (Concurrency 32):** p50 = 1.29s, p95 = 1.34s — **SLO MET ✓**

---

## Key Demonstration Items (Presentation Checklist)

1. **Section 4.1 Difficult Case** — Bank FD named to SEBI correctly routed to RBI  
2. **Multi-Regulator Split** — ASBA IPO dispute triggers mandatory `escalate-to-human`  
3. **Not-Maintainable** — Speculative option losses and sub-judice court cases rejected  
4. **Ingestion Boundary Quarantine** — Malformed payload (bad email, short text) quarantined  
5. **Prompt Injection Guardrail** — "Ignore all previous instructions" blocked at guardrail  
6. **Evidence Verification** — Every citation verified against retrieved passage text  
7. **Evaluation Before/After** — Prompt v1.0 vs v2.0 comparative metric report  
8. **Circuit Breaker Demo** — `POST /api/v1/admin/toggle-circuit-breaker {"force_fail": true}` trips breaker; all subsequent runs fall back gracefully  
9. **Prometheus Metrics** — `GET /metrics` returns live histogram, counter, gauge data  
10. **Token Cost Tracker** — Per-step cost accounting with driver breakdown  

---

## Project Structure

```
securities-grievance-routing/
├── data/
│   ├── corpus/          # Regulatory text documents (SEBI, RBI, IRDAI, PFRDA)
│   ├── index/           # Built vector store & metadata
│   └── eval_cases.json  # 21 labelled evaluation scenarios
├── src/
│   ├── agents/          # TriageAgent, RoutingAgent, Graph, Tools, Verifier
│   ├── api/             # REST routes, rate limiter, HTTP server
│   ├── contracts/       # Complaint & Determination data contracts
│   ├── guardrails/      # Prompt injection, toxicity, output filter
│   ├── llm/             # StubProvider, Client, Prompts, Cost tracker
│   ├── observability/   # Structured logging, Prometheus metrics, Run traces
│   ├── quarantine/      # Rejected payload store
│   ├── queue/           # Async task runner
│   ├── reliability/     # Circuit breaker, Retry, Fallback
│   ├── retrieval/       # Chunker, Embedder, Cache, Vector Index
│   └── config.py        # 12-factor settings
├── web/                 # Browser UI (HTML/CSS/JS)
├── eval/                # Batch evaluation runner & comparative experiment
├── tests/               # Unit/integration test suite + load benchmark
├── grafana/             # Dashboard & datasource provisioning
├── docker-compose.yml   # 6-service production stack
├── Dockerfile
├── prometheus.yml
├── locustfile.py        # Locust HTTP load test
└── .env.example         # Runtime configuration template
```

---

## Team Contributions

| Member | Contribution |
|---|---|
| **Janhavi Rajpurohit** (PES1UG24AM121) | Multi-Agent Graph design, TriageAgent & RoutingAgent implementation, Evidence Verifier, Regulatory Corpus, Evaluation Suite |
| **Kasissnu SSinha** (PES1UG24AM130) | API Gateway, Ingestion Contracts & Quarantine, Guardrails (L4), Circuit Breaker & Reliability, Observability & Prometheus, Docker Compose, Web UI, Load Benchmark |
