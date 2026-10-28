# Presentation Slide Deck
## Securities Investor Grievance Routing Service
### UE24AM342AA5 — ML System Design & AgentOps — Mini Project
**Team:** Janhavi Rajpurohit (PES1UG24AM121) · Kasissnu SSinha (PES1UG24AM130)

---

---

## SLIDE 1 — Title Slide

# Securities Investor Grievance Routing Service
### Multi-Agent Regulatory Triage, Jurisdiction Mapping & Statutory Routing

**Team**
- Janhavi Rajpurohit — PES1UG24AM121
- Kasissnu SSinha — PES1UG24AM130

**Course:** UE24AM342AA5 — ML System Design & AgentOps
**Evaluation 2 — End of Unit 4**

---

---

## SLIDE 2 — Problem Statement

# Problem Statement

> **"Retail investors in India routinely misroute grievances — most commonly filing banking Fixed Deposit disputes with SEBI, which has no jurisdiction over them."**

### The Section 4.1 Difficult Case
A complainant writes:
> *"I invested in a fixed deposit through my bank's app. The interest is lower than promised. I want to complain to SEBI."*

❌ **Wrong:** SEBI SCORES portal assigns a 21-day SLA to the bank  
✅ **Correct:** FDs are governed by **RBI Integrated Ombudsman Scheme** (Clause RBI-IOS-08A)

### Scale of the Problem
- SEBI SCORES processes **50,000+ complaints per year**
- An estimated **30–40% are jurisdictionally misrouted** in the first intake
- Manual triage takes 5–10 minutes per complaint per officer

---

---

## SLIDE 3 — Objectives

# Project Objectives

| # | Objective | Requirement |
|---|---|---|
| 1 | Automatically determine statutory jurisdiction from free-text complaint | F5, F6 |
| 2 | Route to SEBI SCORES 2.0, RBI Ombudsman, IRDAI, PFRDA, or MCA | F5 |
| 3 | Cite the exact clause number verifying the routing decision | A3 |
| 4 | Handle the Section 4.1 difficult case correctly every time | F5 |
| 5 | Mandatorily escalate split-jurisdiction disputes to human review | F7 |
| 6 | Reject malformed intake with field-level validation errors | F2, D1 |
| 7 | Meet p95 latency ≤ 4.0 seconds end-to-end | D6 |
| 8 | Degrade gracefully when the LLM provider is unavailable | A5 |

---

---

## SLIDE 4 — Architecture

# System Architecture

```
┌─────────────────────────────────────────────────────────┐
│   Browser Web UI  (6 Pre-loaded Demo Scenarios)         │
└────────────────────────┬────────────────────────────────┘
                         │ POST /api/v1/complaints
┌────────────────────────▼────────────────────────────────┐
│   REST API Gateway (src/api/main.py)                    │
│   • Schema/Range/Categorical Validation → Quarantine    │
│   • Rate Limiter (15 RPS token bucket)                  │
│   • 202 Accepted + run_id (async)                       │
└────────────────────────┬────────────────────────────────┘
                         │ Task Queue
┌────────────────────────▼────────────────────────────────┐
│   MULTI-AGENT REASONING GRAPH                           │
│                                                         │
│  [Guardrails] Prompt injection / Toxicity screener      │
│       ↓                                                 │
│  [Agent 1: TriageAgent]                                 │
│    Tool 1: corpus_search (vector retrieval)             │
│    Tool 3: request_field_lookup                         │
│    → Identifies: Instrument / Entity / Regulator        │
│       ↓ Hand-off payload                                │
│  [Agent 2: RoutingAgent]                                │
│    Tool 2: clause_lookup (direct ID lookup)             │
│    Tool 1: corpus_search (supplementary retrieval)      │
│    → Statutory adjudication + citation grounding        │
│       ↓                                                 │
│  [Evidence Verifier] Citation ↔ Retrieved text          │
│  [Output Filter] Block judicial award / trading advice  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│   RoutingDetermination                                  │
│   routing_action | citations (verified) | SLA | traces  │
└─────────────────────────────────────────────────────────┘
```

---

---

## SLIDE 5 — Regulatory Corpus & RAG Pipeline

# Regulatory Corpus & RAG Pipeline

### Documents Indexed (42 chunks, 869-dimensional TF-IDF vocabulary)
| Document | Clauses | Regulator |
|---|---|---|
| SEBI Master Circular SCORES 2.0 | 6 | SEBI |
| SEBI (Mutual Funds) Regulations 1996 | 5 | SEBI |
| RBI Integrated Ombudsman Scheme 2021 | 5 | RBI |
| Cross-Regulatory Jurisdiction Guide | 4 | SEBI/RBI/IRDAI/PFRDA/MCA |

### Retrieval Pipeline
1. **Chunking** — Clause-boundary aware (no clause split across chunks)
2. **Embedding** — Offline TF-IDF normalized vectors (zero API cost)
3. **Search** — Cosine similarity with optional regulator filter
4. **Cache** — Two-tier (query-level + full-run-level, SHA-256 keyed)
5. **Verification** — Each citation verified against retrieved chunk text

### Key Capability: Direct Clause Lookup
Agent 2 calls `clause_lookup("RBI-IOS-08A")` directly → returns exact statutory text for citation grounding

---

---

## SLIDE 6 — Section 4.1 Difficult Case Live Demo

# Section 4.1 Difficult Case

### Complaint (Deliberately confusing)
> *"I invested in a fixed deposit through my bank's app. The interest credited is lower than what I was promised. I want to complain to SEBI."*

**Keywords that mislead naive systems:** "invested", "promised", "SEBI"

### What Prompt v1.0 (Baseline) does ❌
- Sees "invested" + "SEBI" → assumes securities market
- Returns: `assign-to-entity` → SEBI, 30-day SLA  
- **WRONG** — this is a banking product, SEBI has no jurisdiction

### What Prompt v2.0 (Production) does ✅
- Rule fires: *"Fixed deposits are banking products under Banking Regulation Act, 1949"*
- Returns: `refer-to-other-regulator` → **RBI Integrated Ombudsman**
- Cites: **Clause RBI-IOS-08A** (Grounds of Complaint — Deposit Accounts)
- Notes: Clause SEBI-CIR-04(e) — banking products explicitly excluded from SEBI

---

---

## SLIDE 7 — Four Routing Outcomes with Examples

# Four Routing Outcomes

| Outcome | When | Example |
|---|---|---|
| `assign-to-entity` | SEBI registered intermediary | Zerodha delayed payout → SEBI SCORES 2.0, 21-day SLA |
| `refer-to-other-regulator` | RBI / IRDAI / PFRDA / MCA | Bank FD interest dispute → RBI cms.rbi.org.in |
| `not-maintainable` | Speculative loss or sub-judice | Nifty options losses / matter before High Court |
| `escalate-to-human` | Split jurisdiction | ASBA IPO: bank blocked funds + broker failed bid upload |

### Split Jurisdiction (F7) — Mandatory Escalation Rule
> *Kotak Bank blocked ₹15,000 for IPO. Broker Upstox missed bid upload deadline. Bank won't release hold without broker confirmation. Both entities blame each other.*

→ Spans **RBI** (SCSB bank lien) + **SEBI** (syndicate broker bid)  
→ System mandatorily routes to `escalate-to-human` citing **CROSS-REG-04**  
→ System is **prohibited** from making a single-regulator determination

---

---

## SLIDE 8 — Reliability & Safety Features

# Reliability & Safety (Requirement A5, L4)

### Circuit Breaker
- Opens after **4 consecutive LLM provider failures**
- Transitions: **CLOSED → OPEN → HALF-OPEN → CLOSED**
- All runs during OPEN state → **Graceful Fallback Path** (never crash, never silent wrong answer)

### Graceful Fallback
- Detects context from complaint text (FD → RBI heuristic, others → escalate)
- Returns a transparently labelled `[DEGRADED FALLBACK DETERMINATION]`
- Always sets `requires_human_escalation = true`

### Prompt Injection Guardrail (L4)
- 12 regex patterns including: "ignore all previous instructions", "system override", "jailbreak mode"
- Injection → immediately blocked → graceful fallback

### Output Filter (L4)
- Blocks judicial award claims, guaranteed settlements, investment advice
- Redacts and escalates — never allows through

---

---

## SLIDE 9 — Evaluation Results (Before vs After)

# Evaluation Results

### 21 Labelled Scenarios × 2 Prompt Variants

| Metric | Baseline (v1.0) | Production (v2.0) | Delta |
|---|---|---|---|
| **Routing Accuracy** | 95.2% | **100.0%** | **+4.8%** |
| **Faithfulness** | 93.8% | **97.1%** | **+3.3%** |
| **Hallucination Rate** | 6.2% | **2.9%** | **−3.3%** |
| **Context Relevance** | 92.9% | 94.3% | +1.4% |
| **Groundedness** | 100.0% | 100.0% | — |

### Deliberate Change Made (L2, L3)
**v1.0:** No cross-regulator boundary check — "invest" + "SEBI" → naively assumes SEBI jurisdiction  
**v2.0:** Added explicit rule — *"Fixed deposits / banking products are NEVER SEBI jurisdiction regardless of vocabulary used"*

### Failures Fixed by v2.0
- TC-01: Bank FD case (was: wrong SEBI assign, now: correct RBI refer)
- TC-18: ASBA split (was: wrong single-entity routing, now: correct escalation)

---

---

## SLIDE 10 — Observability & AgentOps Dashboard

# Observability Stack (Requirement D5)

### Live Metrics (GET /metrics — Prometheus plaintext)
- `agent_runs_total{domain, action}` — runs by routing type
- `agent_run_duration_seconds` — histogram (p50/p95/p99)
- `corpus_freshness_timestamp` — data freshness
- `circuit_breaker_state` — 0=Closed, 1=Half-Open, 2=Open
- `verification_success_total` / `verification_failures_total`
- `cache_hits_total` / `cache_misses_total` — two-tier cache hit rate
- `guardrails_prompt_injections_blocked_total`
- `quarantine_records_total`

### Full Run Reconstruction (D5)
Every run stores: all tool calls, query strings, retrieved passages, prompt version, step latencies, token counts, cost estimate

### Grafana Dashboard (localhost:3000 with docker compose)
10 panels: runs by action, p50/p95/p99 over time, cache hit rates, verification pass/fail, circuit breaker state

---

---

## SLIDE 11 — SLO Benchmark & Feasibility

# SLO Benchmark — Declared vs Actual

**Declared Target:** p95 latency ≤ **4.0 seconds** end-to-end

| Concurrency | Throughput | p50 | p95 | SLO |
|---|---|---|---|---|
| 1 | 12 RPS | 0.083s | 0.085s | ✅ |
| 4 | 22.9 RPS | 0.165s | 0.193s | ✅ |
| 16 | 23 RPS | 0.75s | 0.82s | ✅ |
| **32** | **24.1 RPS** | **1.29s** | **1.34s** | ✅ |

### Financial Feasibility
- Cost per complaint (real LLM at \$0.15/1M tokens): **\$0.000273**
- 100,000 complaints/month: **\$27.30** in LLM tokens
- vs Manual routing: ~**₹2–4 per complaint** (officer time)
- Infrastructure (cloud): **~\$33/month** (API + Redis + monitoring)

### Scaling Path
```bash
docker compose up --scale agent-worker=3  # horizontal scale workers
```

---

---

## SLIDE 12 — GitHub Repository & Project Structure

# GitHub Repository

### 62 Files Committed — `git log`
```
254870c feat: complete Securities Investor Grievance Routing Service
```

### Key Directories
```
securities-grievance-routing/
├── src/agents/        ← Multi-agent graph, Triage, Routing, Tools, Verifier
├── src/retrieval/     ← Chunker, Embedder, Vector Index, Cache
├── src/guardrails/    ← Prompt injection, Toxicity, Output filter
├── src/reliability/   ← Circuit breaker, Retry, Graceful fallback
├── src/observability/ ← Prometheus metrics, JSON logging, Run traces
├── src/api/           ← REST routes, Rate limiter, HTTP server
├── data/corpus/       ← 4 regulatory documents (SEBI/RBI/cross-reg)
├── eval/              ← 21-scenario eval suite + before/after experiment
├── tests/             ← 39 unit/integration tests (all passing)
├── web/               ← Browser UI (HTML/CSS/JS)
└── docker-compose.yml ← 6-service production stack
```

### How to Run (zero-dependency)
```bash
$env:PYTHONPATH = "path\to\securities-grievance-routing"
python -m src.api.main
# → http://localhost:8000
```

---

---

## SLIDE 13 — Live Demo Plan

# Live Demo (5 Minutes)

| Time | Action | Shows |
|---|---|---|
| 0:00 | Open http://localhost:8000 | Web UI |
| 0:30 | Click **Section 4.1 Bank FD** | Correct RBI routing + RBI-IOS-08A citation |
| 1:00 | Click **Broker Payout Delay** | SEBI 21-day SLA + SEBI-CIR-05 |
| 1:30 | Click **Mutual Fund Redemption** | SEBI-MF-REG-53B (15% p.a. interest) |
| 2:00 | Click **Split ASBA IPO** | Mandatory escalate-to-human + CROSS-REG-04 |
| 2:30 | Click **Malformed Request** | 422 Quarantine with per-field error list |
| 3:00 | Click **Prompt Injection** | Blocked by guardrail, graceful fallback |
| 3:30 | `POST /admin/toggle-circuit-breaker` | Circuit OPEN → degraded run |
| 4:00 | `GET /metrics` | Prometheus plaintext output |
| 4:30 | Show eval terminal output | Before/After metric comparison table |

---

---

## SLIDE 14 — Team Contributions

# Team Contributions

| Member | Work |
|---|---|
| **Janhavi Rajpurohit** (PES1UG24AM121) | Multi-Agent Graph architecture, TriageAgent, RoutingAgent, Evidence Verifier, Regulatory Corpus authoring (SEBI/RBI/IRDAI/PFRDA documents), Evaluation suite (21 scenarios + before/after experiment), Prompt engineering (v1.0 → v2.0) |
| **Kasissnu SSinha** (PES1UG24AM130) | REST API & Ingestion Gateway, Data contracts & Quarantine store, Guardrails (L4), Circuit Breaker & Reliability layer, Prometheus metrics & Structured logging, Run reconstruction store, Docker Compose (6-service stack), Grafana dashboard, Web UI (browser client), SLO Load Benchmark |

---

---

## SLIDE 15 — Summary

# Summary

✅ **Multi-agent RAG system** — 2 agents, 3 tools, verifiable statutory citations  
✅ **Section 4.1 Difficult Case** — Bank FD correctly routed to RBI (not SEBI)  
✅ **4 routing outcomes** — assign, refer, not-maintainable, escalate  
✅ **39/39 tests passing** — unit + integration  
✅ **100% routing accuracy** on 21 labelled eval scenarios  
✅ **Prompt v2.0 improvements** — Faithfulness +3.3%, Hallucination −3.3%, Accuracy +4.8%  
✅ **SLO met** — p95 = 1.34s at 32 concurrent clients (declared 4.0s)  
✅ **Production ready** — Docker Compose 6-service stack, Prometheus + Grafana  
✅ **GitHub repository** — 62 files, complete commit history  

**Thank you!**
