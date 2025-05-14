---
title: "M1 – Core runtime & OpenAI adapter"
type: task
status: completed
created: 2025-05-10T10:00:00
updated: 2025-05-12T18:45:00
id: TASK-002
priority: high
memory_types: [procedural, semantic]
dependencies: ["TASK-001"]
tags: [core-runtime, openai, provider-adapter, M1]
---

## Description
Develop the core agent shell runtime and the initial OpenAI provider adapter, as outlined in the PRD.

## Objectives
-   Implement the Turn → Plan → Step DAG execution logic.
-   Emit lifecycle events (e.g., `on_turn_start`, `on_step_end`).
-   Implement configuration-driven personality and provider selection (via `config.toml`).
-   Build the OpenAI provider adapter with uniform async methods: `generate`, `embed`, `moderate`.
-   Include retry mechanisms and exponential backoff for the OpenAI adapter.
-   Integrate basic cost tracking per request for OpenAI.

## Steps
1.  Define core data structures for Turn, Plan, Step. DONE
2.  Implement the asynchronous execution engine for the DAG. DONE (TurnManager, PlanExecutor, StepProcessor logic via events)
3.  Develop the event emission system. DONE (EventEnvelope, Payloads, PubSub)
4.  Implement configuration loading for provider/personality. DONE (ConfigLoader, AppConfig, PersonalityPackManager)
5.  Design and implement the Provider Adapter Interface. DONE (providers/base.py)
6.  Develop the OpenAI adapter, including API calls, error handling, and retries. DONE (providers/openai.py with Tenacity)
7.  Implement token counting and cost calculation for OpenAI calls. DONE (Configurable pricing in config.py, calculation in openai.py, metrics propagation)
8.  Write unit tests for core runtime and OpenAI adapter (target ≥ 85% coverage for `core/` and `providers/` as per PRD). PENDING

## Progress
-   Implemented core runtime classes: `TurnManager`, `PlanExecutor`, `StepProcessor`.
-   Established event-driven flow using `EventPublisherSubscriber` (in-memory).
-   Implemented `TurnManager` logic for starting turns (`start_turn`) and handling step results (`handle_step_result_event`) including state tracking and final event publishing.
-   Implemented `PlanExecutor` to generate plans by prompting an LLM for structured JSON output, including tool/memory descriptions in the prompt, and parsing the JSON into `Step` objects.
-   Implemented `StepProcessor` to execute `LLM_CALL`, `TOOL_CALL`, and `MEMORY_OP` steps based on events.
-   Defined core data models (`Turn`, `Plan`, `Step`, `StepResult`, `Message`, etc.) in `core/models.py`.
-   Defined event structures (`EventEnvelope`, specific payloads) in `core/events.py`.
-   Implemented `ConfigLoader` and Pydantic models for configuration (`core/config.py`).
-   Implemented `ProviderFactory` (`providers/factory.py`).
-   Implemented `PersonalityPackManager` (`core/personality.py`).
-   Implemented `OpenAIAdapter` (`providers/openai.py`) with `generate`, `embed`, `moderate` methods, error handling, retries, and dynamic cost/token calculation based on configuration.
-   Added `StepMetrics` model and integrated metric collection (latency, tokens, cost) into `StepProcessor` and `TurnManager`.
-   Implemented temporary in-memory persistence in `ContextManager` (`get_turn`, `save_turn`) to allow runtime logic to function.
-   Updated relevant Pydantic models and event payloads to support state tracking and metrics.

## Dependencies
-   TASK-001: Architecture sign-off (Completed)

## Notes
-   Owner: Core Eng
-   ETA: 2025-06-05 (as per PRD)

## Next Steps
-   Begin detailed design of core runtime components. 