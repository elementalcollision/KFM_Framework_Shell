---
title: "M3 – Personality pack loader"
type: task
status: completed
created: 2025-05-10T10:00:00
updated: 2025-05-12T20:00:00
id: TASK-004
priority: medium
memory_types: [procedural, semantic]
dependencies: ["TASK-002"]
tags: [personalities, modularity, M3]
---

## Description
Implement the system for loading, managing, and hot-reloading personality packs as defined in the PRD.

## Objectives
-   Define and implement the `Manifest YAML` structure for personality packs (metadata, default traits, version). DONE (via Pydantic models in core/personality.py)
-   Implement loading of prompt layers stored as markdown files. DONE (via system_prompt_file field and loading logic)
-   Integrate optional `tools.py` for function calling capabilities within personality packs. DONE (via execute_tool dynamic loading)
-   Enable hot-reloading of personality packs without server restart, potentially via a `/reload` API endpoint. DONE (via reload_packs method and /management/reload/personalities endpoint)

## Steps
1.  Finalize the schema for the `Manifest YAML` file. DONE (Implicitly via core/personality.py models)
2.  Develop the personality pack discovery and loading mechanism. DONE (core/personality.py)
3.  Implement markdown prompt layer parsing and assembly. DONE (core/personality.py)
4.  Design and implement the interface for `tools.py` integration and execution. DONE (core/personality.py)
5.  Build the hot-reloading functionality, including file watching or an API trigger. DONE (API trigger /management/reload/personalities implemented)
6.  Write unit tests for the personality pack loader and manager. PENDING

## Progress
- [X] Manifest Schema Defined (Pydantic)
- [X] Pack Discovery & Loading Implemented
- [X] Prompt Layer Loading (.md files) Implemented
- [X] Tool Execution (tools.py integration) Implemented
- [X] Hot-Reloading Implemented (Manual API trigger)
- [ ] Unit Tests Pending

## Dependencies
-   TASK-002: Core runtime & OpenAI adapter (core runtime is needed to integrate personality selection)

## Notes
-   Owner: R&D
-   ETA: 2025-07-01 (as per PRD)
-   Consider how personality traits and tools interact with the core prompt generation.

## Next Steps
-   Create example personality pack structures for testing. 