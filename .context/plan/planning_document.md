# Agent Shell Project Plan

**Version:** 0.1
**Date:** 2025-05-10

## 1. Purpose (from PRD Section 1)

Build a **provider-agnostic Agent Shell** that can plug into any LLM-style service API (OpenAI, Google Gemini, Anthropic, Grok, Groq, Cerebras, etc.) and support modular "personality" packs (EAIL, xenomorphic comms, KFM protocols). The shell will become VAST Marketing's reference runtime for chat, content-generation, and autonomous workflows.

## 2. Goals (from PRD Section 3)

1.  **Provider Agnosticism**: Swap back-ends via config/env vars; no code changes.
2.  **Personality Modularity**: Bundle prompts, tools, traits into self-contained packs.
3.  **Production-ready Core**: Minimal primitives (generate, embed, moderate, memory) with async streaming.
4.  **Dev-friendly**: `pip install -e .`, live reload, CLI & FastAPI server out of the box.
5.  **Observability**: Token counts, latency histograms, cost per call.
6.  **Extensible**: New providers or memory stores addable in ≤1 file.

## 3. Milestones & Timeline (from PRD Section 10)

| Milestone                          | Owner        | ETA        | Task ID   |
| ---------------------------------- | ------------ | ---------- | --------- |
| M0 – Architecture sign-off         | Eng Lead     | 2025-05-20 | TASK-001  |
| M1 – Core runtime & OpenAI adapter | Core Eng     | 2025-06-05 | TASK-002  |
| M2 – Anthropic + Groq adapters     | Core Eng     | 2025-06-20 | TASK-003  |
| M3 – Personality pack loader       | R&D          | 2025-07-01 | TASK-004  |
| M4 – Memory service integration    | Platform Eng | 2025-07-15 | TASK-005  |
| M5 – Observability & cost tracking | DevOps       | 2025-07-30 | TASK-006  |
| M6 – Beta launch (internal)        | PO           | 2025-08-05 | TASK-007  |
| M7 – GA                            | PO           | 2025-08-30 | TASK-008  |

## 4. Key Work Areas (Derived from PRD Functional Requirements - Section 7)

*   **Core Runtime Development:** (Relates to M1)
    *   Turn → Plan → Step DAG execution.
    *   Lifecycle event emission.
    *   Config-driven personality & provider selection.
*   **Provider Adapter Layer:** (Relates to M1, M2)
    *   Uniform async methods (`generate`, `embed`, `moderate`).
    *   Retry mechanisms and error handling.
    *   Cost tracking per request.
*   **Personality Packs:** (Relates to M3)
    *   Manifest YAML definition.
    *   Prompt layer storage and `tools.py` integration.
    *   Hot-reloading functionality.
*   **Memory Service:** (Relates to M4)
    *   Pluggable vector store integration.
    *   Short-term caching.
    *   `memory.write`, `memory.search` primitives.
*   **CLI & API Development:**
    *   REPL with streaming.
    *   FastAPI server with `/chat` and `/metrics`.
*   **Containerization & Deployment:**
    *   Dockerfile and probes.
    *   Helm chart (Phase 2).
*   **Observability Implementation:** (Relates to M5)
    *   Structured logging.
    *   Prometheus metrics.

## 5. Task List

Refer to files in `.context/tasks/planned/` for detailed task descriptions. 