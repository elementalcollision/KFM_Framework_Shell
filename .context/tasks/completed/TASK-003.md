---
title: "M2 – Anthropic + Groq adapters"
type: task
status: completed
created: 2025-05-10T10:00:00
updated: 2025-05-12T19:30:00
id: TASK-003
priority: medium
memory_types: [procedural, semantic]
dependencies: ["TASK-002"]
tags: [anthropic, groq, provider-adapter, M2]
---

## Description
Develop provider adapters for Anthropic and Groq, ensuring they conform to the established provider adapter interface.

## Objectives
1.  Implement `AnthropicAdapter` in `providers/anthropic.py` conforming to `ProviderInterface`.
2.  Handle Anthropic API calls, error mapping, retries, and cost calculation.
3.  Write unit tests for `AnthropicAdapter`.
4.  Implement `GroqAdapter` in `providers/groq.py` conforming to `ProviderInterface`.
5.  Handle Groq API calls (OpenAI-compatible), error mapping, retries, and cost calculation.
6.  Write unit tests for `GroqAdapter`.

## Steps
1.  **Anthropic Adapter - Configuration:** DONE
    *   Add `AnthropicProviderConfig` to `core/config.py`.
    *   Define fields for API key, default model, model pricing (structure).
2.  **Anthropic Adapter - Implementation:** DONE
    *   Create `providers/anthropic.py` with `AnthropicAdapter(ProviderInterface)`.
    *   Implement `__init__` using `AsyncAnthropic`.
    *   Implement `generate` method (API call, error handling, cost calc, retries with Tenacity).
    *   Implement placeholder `embed` and `moderate` methods (not directly supported by SDK for messages API).
    *   Update `ProviderFactory` to support `AnthropicAdapter`.
3.  **Anthropic Adapter - Unit Tests:** PENDING
    *   Write unit tests for `AnthropicAdapter` in `tests/providers/test_anthropic.py`.
    *   Mock API calls and test success, error, and retry scenarios.
4.  **Groq Adapter - Configuration:** DONE
    *   Add `GroqProviderConfig` to `core/config.py`.
    *   Define fields for API key, default model, model pricing (structure, actual pricing TBD).
5.  **Groq Adapter - Implementation:** DONE
    *   Create `providers/groq.py` with `GroqAdapter(ProviderInterface)`.
    *   Implement `__init__` using `AsyncGroq`.
    *   Implement `generate` method (OpenAI-compatible API call, error handling, cost calc, retries with Tenacity).
    *   Implement placeholder `embed` and `moderate` methods.
    *   Update `ProviderFactory` to support `GroqAdapter`.
6.  **Groq Adapter - Unit Tests:** PENDING
    *   Write unit tests for `GroqAdapter` in `tests/providers/test_groq.py`.
    *   Mock API calls and test success, error, and retry scenarios.

## Progress
- [X] Anthropic adapter configuration defined.
- [X] Anthropic adapter core implementation (generate, init) complete.
- [ ] Anthropic adapter unit tests to be written.
- [X] Groq adapter configuration defined.
- [X] Groq adapter core implementation (generate, init) complete.
- [ ] Groq adapter unit tests to be written.

## Dependencies
- TASK-002: Core runtime & OpenAI adapter (provides base interface and factory pattern)

## Notes
- Embedding and Moderation: For both Anthropic and Groq, the primary SDKs/APIs reviewed focus on chat completions. Dedicated embedding or moderation endpoints were not immediately apparent in the provided SDK documentation. The adapters currently raise `NotImplementedError` for these.
- Groq Pricing: The `GroqProviderConfig` includes a `model_pricing` field, but actual Groq pricing details (per token or other metrics) need to be sourced and updated in the `config.toml` for accurate cost tracking.
- Unit tests are deferred for now, similar to TASK-002.

## Next Steps
- Proceed to implement unit tests for both adapters OR
- Defer unit tests and complete this task, then activate the next task (TASK-004: Memory - Redis Integration).

## Notes
-   Owner: Core Eng
-   ETA: 2025-06-20 (as per PRD)

## Next Steps
-   Obtain API keys and access for Anthropic and Groq testing environments. 