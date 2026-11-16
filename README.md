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


### Using a Real LLM (Gemini / OpenAI / OpenAI-compatible)
By default `LLM_PROVIDER=stub`: a deterministic keyword-rule provider used for offline demos, CI and
load tests. It is **not** a language model. To route complaints with a real model, copy `.env.example`
to `.env` (loaded automatically, never committed) and set:

```bash
# Google Gemini (free key: https://aistudio.google.com/apikey)
LLM_PROVIDER=gemini
LLM_API_KEY=<your key>
LLM_MODEL=            # empty = gemini-flash-latest

# OpenAI
LLM_PROVIDER=openai
LLM_API_KEY=<your key>
LLM_MODEL=            # empty = gpt-4o-mini

# Any OpenAI-compatible API, e.g. Groq or a local Ollama (no key needed)
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.1
```

How it works (`src/llm/client.py`, `src/llm/providers.py`, `src/llm/prompts.py`):
- Both agents send the versioned system prompt (`v1.0` / `v2.0`) plus a shared JSON output contract,
  with temperature 0 and JSON mode. The complaint is wrapped in `<complaint>` tags and marked as untrusted data.
- The routing agent receives the retrieved passages with their `clause_id`s and must cite one of them.
  The existing `EvidenceVerifier` then checks the citation against the corpus, and an invented clause escalates to a human.
- Model output is normalized: an unknown `routing_action` fails safe to `escalate-to-human`.
- 429 / 5xx / timeouts / malformed JSON raise retryable errors (retry + circuit breaker apply); auth errors do not retry.
- Real token counts are recorded in the cost ledger. Set `LLM_COST_PER_1M_INPUT` / `LLM_COST_PER_1M_OUTPUT` to your model's price.
- `GET /health` reports the active provider and model. The eval prints it too.
- If a real provider is configured without a key, the service logs a warning and uses the stub.

Unit tests always force the stub, so they never call a paid API.

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
# Full unit + integration test suite (44 tests)
python -m unittest tests.test_suite -v

# Evaluation suite (21 scenarios × 2 prompt variants — L2, L3)
python -m eval.run_eval

# SLO Load Test Benchmark (D6, A7)
python tests/load_test_benchmark.py
```

### Evaluation Results — Real LLM (Gemini, Prompt v1.0 Baseline → v2.0 Production)
Measured with `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-flash-lite-latest`, temperature 0,
21 scenarios from `data/eval_cases.json` (`python -m eval.run_eval`, run on 2026-11-16).

| Metric | Baseline v1.0 | Production v2.0 | Delta |
|---|---|---|---|
| Routing Accuracy | 81.0% | **100.0%** (21/21) | +19.1% |
| Faithfulness | 84.5% | **97.9%** | +13.3% |
| Hallucination Rate | 15.5% | **2.1%** | −13.3% |
| Context Relevance | 90.0% | **94.3%** | +4.3% |
| Groundedness | 100.0% | 100.0% | — |

**Deliberate change:** Added explicit cross-regulator banking-vs-securities boundary rule and mandatory split-jurisdiction escalation in Prompt v2.0.

Notes on interpreting these numbers:
- During the run Gemini returned intermittent `503 high demand` errors. 3 of the 4 v1.0 misses were runs where
  every retry hit a 503 and the service correctly degraded to `escalate-to-human`, so the true v1.0 gap is smaller than shown.
- Routing accuracy is an exact match against the expected action. Faithfulness and hallucination rate are rule-based scores
  derived from routing and cited-clause matches (see `eval/run_eval.py`), not LLM-judged.
- Run time: ~6.5 minutes for 63 runs (126 LLM calls), throttled to `LLM_MAX_RPM=10` for the free tier.

With the offline deterministic stub (`LLM_PROVIDER=stub`, keyword rules, no AI) the same suite scores 95.2% → 100.0%.

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
