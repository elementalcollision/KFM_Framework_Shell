---
title: "M5 – Observability & cost tracking"
type: task
status: completed
created: 2025-05-10T10:00:00
updated: 2025-05-13T14:32:15
id: TASK-006
priority: medium
memory_types: [procedural]
dependencies: ["TASK-002"]
tags: [observability, metrics, cost-tracking, M5]
---

## Description
Implement comprehensive observability features, including structured logging, Prometheus metrics, and detailed cost tracking, as per the PRD.

## Objectives
-   Implement structured logs (JSON) with a unique `turn_id` for tracing requests.
-   Set up Prometheus metrics: `llm_request_latency_seconds`, `llm_tokens_total` (count and $ value), `llm_errors_total`.
-   Ensure cost tracking per request is accurate and covers all integrated providers.
-   Expose metrics via a `/metrics` endpoint for Prometheus scraping.

## Steps
1.  Define the structured log schema, including `turn_id` and other relevant fields.
2.  Integrate structured logging throughout the core runtime and provider adapters.
3.  Set up Prometheus client library and define the required metrics.
4.  Instrument code to collect and expose latency, token counts, and error metrics.
5.  Enhance provider adapters to report detailed token usage for cost calculation.
6.  Develop the `/metrics` endpoint in the FastAPI server.
7.  Validate accuracy of metrics, especially cost calculations against provider price sheets.

## Progress
-   [X] Structured JSON Logging Implemented
-   [X] Prometheus Metrics Configured
-   [X] Cost Tracking in Provider Adapters
-   [X] Trace ID Propagation
-   [X] Metrics Endpoint (/metrics) Exposed
-   [X] Unit Tests Written

## Dependencies
-   TASK-002: Core runtime & OpenAI adapter (metrics and logging will be integrated into the core system)

## Notes
-   Owner: DevOps
-   ETA: 2025-07-30 (as per PRD)
-   Close collaboration with Core Eng will be needed for metric instrumentation.

## Next Steps
-   None. Task complete. 