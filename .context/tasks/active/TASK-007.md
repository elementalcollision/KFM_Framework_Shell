---
title: "M6 – Beta launch (internal)"
type: task
status: active
created: 2025-05-10T10:00:00
updated: 2025-05-13T13:06:24
id: TASK-007
priority: high
memory_types: [procedural, episodic]
dependencies: ["TASK-003", "TASK-004", "TASK-005", "TASK-006"]
tags: [launch, beta, M6]
---

## Description
Prepare for and execute the internal beta launch of the Agent Shell to gather initial user feedback and validate core functionality.

## Objectives
-   Ensure all preceding milestone features (M1-M5) are stable and integrated.
-   Prepare user documentation and guides for internal beta testers (Content Strategists, Researchers).
-   Set up a feedback collection mechanism.
-   Conduct the internal beta testing period.
-   Meet acceptance criteria: Config Swap, Personality Hot-load, Streaming, Cost Metric visibility, Unit Coverage.

## Steps
1.  Perform integration testing of all developed features (core runtime, adapters, personalities, memory, observability).
2.  Draft initial user guides and API documentation.
3.  Identify and onboard internal beta testers.
4.  Deploy a stable beta version to a testing environment.
5.  Run a structured beta testing program, collect feedback, and identify issues.
6.  Verify all PRD Acceptance Criteria are met.

## Progress
- [✓] Verified all dependencies are completed (TASK-003, TASK-004, TASK-005, TASK-006)
- [✓] Initial transition to beta phase approved
- [✓] Integration testing of all components
  - [✓] Core Runtime & Personality Packs integration tests
  - [✓] Memory tools integration tests
  - [✓] API-to-Runtime integration tests
  - [ ] Remaining component integrations
- [↻] User documentation and guides for beta testers (Draft created, pending final details)
- [ ] Feedback collection mechanism
- [ ] Beta tester onboarding
- [↻] Deploy to testing environment (In progress)
- [ ] Verify acceptance criteria

## Dependencies
-   TASK-003: Anthropic + Groq adapters
-   TASK-004: Personality pack loader
-   TASK-005: Memory service integration
-   TASK-006: Observability & cost tracking

## Notes
-   Owner: PO (Product Owner)
-   ETA: 2025-08-05 (as per PRD)

## Next Steps
-   Finalize user documentation for beta testers (fill in pending details)
-   Set up feedback collection mechanism
-   Onboard beta testers
-   Continue comprehensive testing of all integration points (if any further components are identified) 