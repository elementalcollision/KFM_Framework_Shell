# Agent Shell – Product Requirements Document (PRD)

> **Version 0.1 · Draft** | May 10 2025 | Author: Dave Graham (with ChatGPT)

---

## 0. Revision History

| Date       | Version     | Author      | Notes                     |
| ---------- | ----------- | ----------- | ------------------------- |
| 2025‑05‑10 | 0.1 (Draft) | Dave Graham | Initial outline generated |

---

## 1. Purpose

Build a **provider‑agnostic Agent Shell** that can plug into any LLM‑style service API (OpenAI, Google Gemini, Anthropic, Grok, Groq, Cerebras, etc.) and support modular “personality” packs (EAIL, xenomorphic comms, KFM protocols). The shell will become VAST Marketing’s reference runtime for chat, content‑generation, and autonomous workflows.

---

## 2. Background & Problem Statement

* Current experiments with multiple LLM vendors result in copy‑pasted glue code and siloed prompt logic.
* Personality research (EAIL, xenomorphic, KFM) lives in separate repos, making A/B tests painful.
* We need a **single orchestrator**—language & provider neutral—that frontline teams can extend without touching infra.

---

## 3. Goals

1. **Provider Agnosticism** – swap back‑ends via config/env vars; no code changes.
2. **Personality Modularity** – bundle prompts, tools, traits into self‑contained packs.
3. **Production‑ready Core** – minimal primitives (generate, embed, moderate, memory) with async streaming.
4. **Dev‑friendly** – `pip install -e .`, live reload, CLI & FastAPI server out of the box.
5. **Observability** – token counts, latency histograms, cost per call.
6. **Extensible** – new providers or memory stores addable in ≤1 file.

---

## 4. Non‑Goals

* End‑user UX (chat UI) – handled by separate front‑end projects.
* Fine‑tuning models – out of scope for MVP.
* Vendor billing automation – future phase.

---

## 5. Stakeholders

| Role             | Name / Team         | Responsibility                  |
| ---------------- | ------------------- | ------------------------------- |
| Product Owner    | Dave Graham         | Scope, prioritization           |
| Engineering Lead | TBD (Platform Eng)  | Architecture & code reviews     |
| Researchers      | EAIL / KFM R\&D     | Supply personality packs        |
| Users            | Content Strategists | Consume CLI / API for campaigns |
| Infra / DevOps   | Platform Ops        | Deploy, monitor, secure         |

---

## 6. Personas & Key User Stories

1. **Prompt Hacker (Paula)** – “I want to hot‑swap between GPT‑4o and Claude‑Opus while iterating on a campaign prompt.”
2. **Researcher (Raj)** – “I need to publish a new ‘xeno‑bridge’ personality without touching deployment pipelines.”
3. **DevOps (Dana)** – “I require clear metrics for token spend and error rates across vendors.”
4. **Product Manager (Pat)** – “I want to track milestones and acceptance criteria in Jira/Linear.”

---

## 7. Functional Requirements

\### 7.1 Core Runtime

* Execute a **Turn → Plan → Step** DAG asynchronously.
* Emit lifecycle events (`on_turn_start`, `on_step_end`, `on_error`).
* Config‑driven personality & provider selection (`config.toml`).

\### 7.2 Provider Adapter Layer

* Uniform async methods: `generate`, `embed`, `moderate`.
* Retry + exponential backoff; surface vendor error codes.
* Cost tracking per request (tokens × price sheet).

\### 7.3 Personality Packs

* **Manifest YAML** with metadata, default traits, and version.
* Prompt layers stored as markdown; optional `tools.py` for function calls.
* Hot‑reload without server restart.

\### 7.4 Memory Service

* Pluggable vector store (`pgvector`, `Weaviate`, `Vespa`).
* Short‑term cache layer (Redis) with TTL support.
* `memory.write`, `memory.search` primitives.

\### 7.5 CLI

* REPL with streaming tokens.
* Flags: `--provider`, `--model`, `--personality`, `--trace`.

\### 7.6 FastAPI Server

* `/chat` WebSocket endpoint (streams chunks).
* `/metrics` Prometheus scrape.
* OpenAPI‑generated docs.

\### 7.7 Containerization & Deployment

* Dockerfile; readiness & liveness probes.
* Helm chart (phase 2) for Kubernetes.
* Environment‑based secret injection.

\### 7.8 Observability

* Structured logs (JSON) with `turn_id`.
* Prom metrics: `llm_request_latency_seconds`, `llm_tokens_total`, `llm_errors_total`.

---

## 8. Non‑Functional Requirements

| Category        | Requirement                                                 |
| --------------- | ----------------------------------------------------------- |
| **Performance** | ≤ 150 ms overhead beyond provider latency for a single step |
| **Scalability** | Handle 50 concurrent turns on a 2‑CPU container             |
| **Reliability** | 99.5 % uptime; retries on transient provider errors         |
| **Security**    | Secrets via Secret Manager; per‑tenant namespace in caches  |
| **Portability** | Runs on CPython 3.12, Linux amd64 & arm64                   |
|                 |                                                             |

---

## 9. Success Metrics / KPIs

* **Time‑to‑Integrate** – new provider adapter in ≤ 2 engineering days.
* **Personality Publish Cycle** – pack → prod in ≤ 30 minutes.
* **Cost Overrun** – < 3 % variance between estimated and actual token spend.
* **Mean Turn Latency** – p95 ≤ 2 s for 2‑step plans.

---

## 10. Milestones & Timeline *(target)*

| Milestone                          | Owner        | ETA        |
| ---------------------------------- | ------------ | ---------- |
| M0 – Architecture sign‑off         | Eng Lead     | 2025‑05‑20 |
| M1 – Core runtime & OpenAI adapter | Core Eng     | 2025‑06‑05 |
| M2 – Anthropic + Groq adapters     | Core Eng     | 2025‑06‑20 |
| M3 – Personality pack loader       | R\&D         | 2025‑07‑01 |
| M4 – Memory service integration    | Platform Eng | 2025‑07‑15 |
| M5 – Observability & cost tracking | DevOps       | 2025‑07‑30 |
| M6 – Beta launch (internal)        | PO           | 2025‑08‑05 |
| M7 – GA                            | PO           | 2025‑08‑30 |

---

## 11. Acceptance Criteria

1. **Config Swap** – Changing `provider` in `config.toml` and restarting the server routes traffic to the new vendor.
2. **Personality Hot‑load** – Adding a folder under `personalities/` and POSTing `/reload` API makes it available in live chat.
3. **Streaming** – WebSocket client receives tokens in < 250 ms intervals.
4. **Cost Metric** – `llm_tokens_total` & `$` value appear in Prometheus.
5. **Unit Coverage** – ≥ 85 % lines in `core/` and `providers/`.

---

## 12. Risks & Mitigations

| Risk                                  | Impact             | Mitigation                                    |
| ------------------------------------- | ------------------ | --------------------------------------------- |
| Vendor API drift                      | Breaks adapters    | Contract tests in CI; wrapper version pinning |
| Token cost spikes                     | Budget overruns    | Daily spend alerts; per‑turn hard token limit |
| Prompt injection in personality packs | Security/data‑leak | Pack linting + content moderation layer       |

---

## 13. Dependencies

* Provider API keys & quotas (OpenAI, Anthropic, etc.).
* Redis & Vector DB clusters.
* DevOps monitoring stack (Grafana, Prometheus).

---

## 14. Open Questions / Next Steps

1. Which vector store (pgvector vs Weaviate) fits VAST infra best?
2. Do we need per‑tenant isolation on Day 1 or post‑MVP?
3. How will billing data integrate with Finance dashboards?
4. Finalize security review for multi‑vendor secrets management.

---

**Call to Action:** Review this PRD in the upcoming sprint‑planning session and create Jira epics/stories aligned with the milestones above.
