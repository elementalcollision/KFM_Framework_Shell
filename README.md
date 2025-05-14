# KFM Agent Shell: Architecture Overview

## 1. Introduction

This document outlines the architecture for the KFM Agent Shell project, a modular, event-driven system designed for high performance and provider agnosticism. It leverages Apache Iggy as its central message streaming backbone, replacing a traditional Kafka-based message bus. The architecture emphasizes decoupled components, hot-loadable personalities, and comprehensive observability.

## 2. Core Architecture Principles

The Agent Shell is built upon the following foundational principles:

* **Decoupled Components**: Each architectural component operates independently, communicating via well-defined interfaces.
* **Event-Driven Communication**: Asynchronous event streams via Apache Iggy enable loose coupling and resilient communication.
* **Provider Abstraction**: A uniform interface allows interaction with multiple Large Language Model (LLM) vendors without tying the core system to a specific provider.
* **Personality Modularity**: Agent personalities are designed as self-contained "packs" that can be dynamically loaded and updated (hot-loaded).
* **Observability First**: The system is designed with comprehensive metrics, structured logging, and distributed tracing capabilities from the ground up.
* **Scalable Design**: The architecture supports horizontal scaling through stateless components and the efficient partitioning capabilities of Apache Iggy.

## 3. Component Architecture

The KFM Agent Shell is composed of several key layers and services that work in concert:

### 3.1. Core Runtime Layer

* **Purpose**: Serves as the central orchestrator for the Agent Shell, managing the end-to-end `"Turn -> Plan -> Step"` workflow. It receives user input, coordinates with various services (LLM providers via Provider Adapter Layer, Memory Service, Personality Pack Manager), and directs the generation of an agent response.
* **Design**: Designed to be stateless where possible, relying on Apache Iggy for event-driven communication and state progression, and the Memory Service for persistent context.
* **Sub-Modules**:
    * **ConfigLoader**: Loads, validates, and provides access to system configuration (from `config.toml`), including secure handling of secrets from environment variables and optional hot-reloading.
    * **TurnManager**: Manages the lifecycle of a single user interaction ("turn"), including personality selection, context initialization, and orchestration of the PlanExecutor.
    * **PlanExecutor**: Generates a structured execution plan (e.g., a sequence of steps) to address the user's request. This may involve LLM prompting, plan validation, and breaking the plan into discrete steps.
    * **StepProcessor**: Executes individual steps defined in the plan. Step types include LLM calls, tool invocations, memory operations, and external API calls. It manages step state, streaming of partial results, and error handling, including potential compensating actions.
    * **ContextManager**: Manages the in-memory state for the current active turn and acts as a bridge to the MemoryService for retrieving and persisting long-term user context and conversation history.
    * **EventPublisherSubscriber**: A thin, robust wrapper around the Apache Iggy Python client, handling the publishing of all internal/external events and managing subscriptions to Iggy streams.
* **Workflow Diagram (Conceptual - from PDF Page 2)**:
    ```mermaid
    graph TD
        subgraph Core Runtime Layer
            APILayerInput[API Layer Input via Iggy] --> TurnManager;
            TurnManager --> ContextManager;
            TurnManager --> PersonalityPackManagerInterface[Personality Pack Manager];
            TurnManager --> PlanExecutor;
            ContextManager --> MemoryServiceInterface[Memory Service];
            PlanExecutor --> ProviderAdapterLayerInterface[Provider Adapter Layer];
            PlanExecutor --> ContextManager;
            PlanExecutor --> StepProcessor[Step Events via Iggy];
            StepProcessor --> ProviderAdapterLayerInterface;
            StepProcessor --> PersonalityPackManagerInterface;
            StepProcessor --> ContextManager;
            StepProcessor --> APILayerOutput[API Layer Output / Streaming];
            ConfigLoader --> TurnManager;
            ConfigLoader --> PlanExecutor;
            ConfigLoader --> StepProcessor;
            EventPublisherSubscriber --> Iggy[Apache Iggy];
            TurnManager --> EventPublisherSubscriber;
            PlanExecutor --> EventPublisherSubscriber;
            StepProcessor --> EventPublisherSubscriber;
        end
    ```

### 3.2. Provider Adapter Layer

* **Purpose**: Provides a single, consistent asynchronous interface for the Core Runtime to interact with any supported LLM provider, abstracting away provider-specific API details.
* **Responsibilities**: Adapts generic requests into provider-specific calls, maps responses/errors to a standardized format, enables extensibility for new providers, implements resilience (retries), tracks costs, and normalizes errors.
* **Sub-Modules**:
    * **ProviderFactory**: Dynamically instantiates the correct provider adapter.
    * **ProviderInterface (ABC)**: Defines the contract for adapters (e.g., `async generate()`, `async embed()`).
    * **ConcreteAdapters** (e.g., `OpenAIAdapter`, `AnthropicAdapter`): Implement the interface for specific vendors.
    * **RetryHandler**: Implements retry logic (e.g., exponential backoff).
    * **CostTracker**: Calculates estimated LLM call costs.
    * **ErrorNormalizer**: Maps provider errors to standard types.
* **Diagram (Conceptual - from PDF Page 15-16)**:
    ```mermaid
    graph TD
        subgraph Provider Adapter Layer
            direction TB
            PF[ProviderFactory]
            PI[Provider Interface ABC]
            CA[ConcreteAdapters e.g., OpenAIAdapter]
            RH[RetryHandler]
            CT[CostTracker]
            EN[ErrorNormalizer]

            PF --> PI;
            PI --> CA;
            CA --> RH;
            CA --> CT;
            CA --> EN;
        end
        CoreRuntime[Core Runtime] --> |Request LLM Call| PF;
        CA --> |Standardized Response/Error| CoreRuntime;
        CA --> |Native API Calls| ExtLLMAPIs[External LLM APIs];
        ExtLLMAPIs --> |Native Responses/Errors| CA;
    ```

### 3.3. Personality Pack Manager

* **Purpose**: Manages the loading, validation, and runtime availability of "personality packs," which define an agent's specific behavior, prompts, tools, and knowledge.
* **Responsibilities**: Scans for packs, parses/validates `manifest.yaml` files, handles hot-reloading of packs, maintains a registry of available personalities, and constructs `PersonalityInstance` objects for the Core Runtime.
* **Structure**: A personality pack is a directory containing:
    * `manifest.yaml`: Defines metadata, default LLM settings, system prompt, tools, and knowledge configuration.
    * `prompts/`: Directory for prompt templates (e.g., `system_prompt.md`).
    * `tools/`: Python module(s) defining custom tools available to the personality.
    * `knowledge/` (Optional): Files for Retrieval Augmented Generation (RAG).
* **Security Note**: Tool execution requires robust sandboxing (e.g., Wasm, MicroVMs) as a critical security measure.
* **Diagram (Conceptual - from PDF Page 19-20)**:
    ```mermaid
    graph TD
        subgraph Personality Pack Manager as PPM
            PL[Pack Loader]
            MPV[Manifest Parser & Validator]
            HRC[Hot-Reload Controller]
            PR[Pack Registry]
            PIF[PersonalityInstance Factory]

            PL --> MPV;
            MPV --> PIF;
            HRC --> PL;
            HRC --> PR;
            PIF --> PR;
        end
        subgraph Filesystem
            PP[Personality Packs Directory e.g., personalities/]
        end
        CRT[Core Runtime (TurnManager)] --> |Request PersonalityInstance| PR;
        PR --> |Return PersonalityInstance| CRT;
        PPM --> |Scans, Loads| PP;
    ```

### 3.4. Memory Service

* **Purpose**: Provides persistent and temporary memory capabilities, supporting conversation history, user context/preferences, and knowledge bases for RAG.
* **Responsibilities**: Stores and retrieves user-specific context, manages indexing and retrieval of knowledge documents for RAG, provides a caching layer, and abstracts underlying storage technologies.
* **Sub-Modules**:
    * **MemoryOperations (Interface & Orchestration)**: Defines high-level memory operations and coordinates calls to VectorStoreAdapter and CacheLayer.
    * **VectorStoreAdapter**: Provides a consistent interface to various vector DB backends (e.g., Postgres/pgvector, Weaviate) for storing and searching embeddings.
    * **CacheLayer**: Provides caching (e.g., Redis) for frequently accessed data like session context.
    * **TTLManager**: Manages Time-To-Live for cached items.
* **Diagram (Conceptual - from PDF Page 25-26)**:
    ```mermaid
    graph TD
        subgraph Memory Service
            MO[Memory Operations Interface]
            VSA[Vector Store Adapter]
            CL[Cache Layer]
            TTL[TTL Manager]

            MO --> VSA;
            MO --> CL;
            CL --> TTL;
        end
        CRT_ContextManager[Core Runtime (ContextManager)] --> |CRUD, RAG Queries| MO;
        PPM_PIF[Personality Pack Manager (PersonalityInstanceFactory)] --> |RAG Setup| MO;
        VSA --> VDB[(Vector DB e.g., Postgres/pgvector)];
        CL --> Cache[(Cache e.g., Redis)];
    ```

### 3.5. Apache Iggy Integration Layer

* **Purpose**: Responsible for seamless integration of Apache Iggy as the central message streaming platform. It abstracts Iggy-specific details and provides a clear interface for other components.
* **Responsibilities**: Facilitates all asynchronous inter-component communication, abstracts the Iggy Python SDK, manages connection configurations, defines stream/topic management (though creation might be external), and ensures reliable messaging patterns.
* **Sub-Modules/Areas**:
    * **Client Abstraction (e.g., `IggyBrokerClient`)**: Wraps the native Iggy Python SDK, manages connections, provides simplified publish/subscribe methods, and handles serialization/deserialization.
    * **Stream & Topic Manager**: Defines canonical streams/topics, partitioning strategies, and retention policies.
    * **Consumer Group Coordinator**: Manages consumer group definitions for load balancing and parallel processing.
* **Key Iggy Features Leveraged**: Streams, Topics, Partitions, Persistent Append-only Log, Consumer Groups, Message Polling, Multiple Transport Protocols (TCP, QUIC, HTTP), Python SDK, Security (TLS, Auth).
* **Diagram (Conceptual - from PDF Page 30)**:
    ```mermaid
    graph TD
        subgraph Apache Iggy Integration Layer
            CA[Client Abstraction - IggyClient Wrapper]
            STM[Stream & Topic Manager]
            CGC[Consumer Group Coordinator]
        end
        CoreRuntime_EPS[Core Runtime (EventPublisherSubscriber)] --> |Publish/Subscribe| CA;
        OtherComponents --> |Publish/Subscribe| CA;
        CA --> |Uses| IggySDK[Iggy Python SDK];
        IggySDK --> IggyServer[(Apache Iggy Server)];
        STM -.-> |Configures| IggyServer;
        CGC -.-> |Manages Consumers on| IggyServer;
    ```

### 3.6. API and Interface Layer

* **Purpose**: Provides external access to the Agent Shell's functionalities for users (e.g., via CLI, Web UI), developers (Xenocomm SDK), and other systems (Machine-to-Component Protocol - MCP).
* **Responsibilities**: Exposes functionality via well-defined interfaces, handles user interaction, provides robust APIs for programmatic access, supports real-time communication (WebSockets), ensures consistent data formats/error handling, and implements security (auth, rate limiting).
* **Sub-Modules**:
    * **FastAPI Server**: Serves RESTful APIs, Xenocomm HTTP endpoints, and potentially a web admin UI.
    * **WebSocket Handler**: Manages persistent WebSocket connections for interactive chat, streaming responses, and Xenocomm real-time features. Scaled using a Redis Pub/Sub backplane.
    * **gRPC Server**: Provides high-performance, schema-defined (Protobuf) APIs for Xenocomm SDK and MCP.
    * **CLI Interface**: Command-line tools for developers and administrators.
    * **Authentication Service (Cross-cutting)**: Handles authentication (OAuth 2.1 with JWTs, API keys).
    * **Rate Limiting Service (Cross-cutting)**: Implements rate limiting policies.
* **Diagram (Conceptual - from PDF Page 36)**:
    ```mermaid
    graph LR
        subgraph External Interfaces
            User[External Users/Systems]
            SDK[Xenocomm SDK Clients]
            CLIUser[CLI Users]
            MCPClient[Other Machines/Components (MCP)]
        end
        subgraph API and Interface Layer
            direction TB
            FAS[FastAPI Server]
            WSH[WebSocket Handler]
            GRPCS[gRPC Server]
            CLII[CLI Interface]
            CrossCutting[Auth & Rate Limiting]

            FAS --- CrossCutting;
            WSH --- CrossCutting;
            GRPCS --- CrossCutting;
            CLII --- CrossCutting;
        end
        User --> FAS;
        User --> WSH;
        SDK --> GRPCS;
        SDK --> FAS;
        CLIUser --> CLII;
        MCPClient --> GRPCS;
        FAS --> Services[Core Runtime & Other Services];
        WSH --> Services;
        GRPCS --> Services;
        CLII --> Services;
    ```

### 3.7. Observability Layer

* **Purpose**: Enables comprehensive monitoring, logging, tracing, and debugging of the Agent Shell system.
* **Responsibilities**: Gathers logs, metrics, traces, and cost data; standardizes data formats (JSON logs, Prometheus exposition, OpenTelemetry); exposes data to monitoring tools; provides health monitoring.
* **Sub-Modules/Areas**:
    * **Structured Logger (`structlog`)**: Ensures all components produce structured JSON logs with rich context (including `trace_id`).
    * **Metrics Collector (Prometheus)**: Collects and exposes metrics via `/metrics` endpoints (system, application, Iggy, LLM, personality, cost).
    * **Trace Manager (OpenTelemetry)**: Implements distributed tracing, propagating context across components (including Iggy messages) and exporting to backends (Tempo, Jaeger).
    * **Cost Tracker Integration**: Output from Provider Adapter Layer is fed into metrics and logs.
    * **Health Monitor**: Components expose `/health/live` and `/health/ready` endpoints.
* **Integration**: Primarily with Prometheus for metrics and Grafana for dashboards and alerts, utilizing Loki for logs and Tempo/Jaeger for traces, all correlated via `trace_id`.
* **Diagram (Conceptual - from PDF Page 40-41)**:
    ```mermaid
    graph TD
        subgraph Observability Layer
            SL[Structured Logger (structlog)]
            MC[Metrics Collector (Prometheus Exp.)]
            TM[Trace Manager (OpenTelemetry)]
            CTD[Cost Tracker Data Input]
        end
        subgraph External Systems
            LogAgg[Log Aggregation (e.g., Loki)]
            Prom[Prometheus Server]
            TraceBE[Tracing Backend (e.g., Tempo)]
            Graf[Grafana]
        end
        AgentShellComponents --> SL;
        AgentShellComponents --> MC;
        AgentShellComponents --> TM;
        ProviderAdapterLayer_CostTracker --> CTD;
        CTD --> MC;
        CTD --> SL;

        SL --> |Logs (JSON)| LogAgg;
        MC --> |Metrics (/metrics)| Prom;
        TM --> |Traces (OTLP)| TraceBE;

        Prom --> Graf;
        LogAgg --> Graf;
        TraceBE --> Graf;
    ```

## 4. Data Flow and Message Schemas

Communication within the Agent Shell, particularly events via Apache Iggy, adheres to defined message structures (JSON Schema 2020-12) for interoperability.

* **Common Event Envelope**: All Iggy events share an envelope with fields like `event_id`, `type`, `spec_version` (for payload schema versioning), `timestamp`, and `trace_id`. The actual event data is in the `payload` object.
    ```json
    // CommonEventEnvelope-v1 Example
    {
      "event_id": "ulid-or-uuid",
      "type": "TurnEvent.v1", // Example event type
      "spec_version": "1.0.0", // Version of the payload schema
      "timestamp": "iso-8601-datetime",
      "trace_id": "opentelemetry-trace-id",
      "tenant_id": "optional-tenant-id",
      "session_id": "optional-session-id",
      "payload": {
        // Type-specific payload object
      }
    }
    ```
* **Key Event Payloads**:
    * **`TurnEvent.v1`**: (Topic: `agent.turns.requests`) Initiates a user interaction. Contains `turn_id`, `user_message`, `personality_id`.
    * **`StepEvent.v1`**: (Topic: `agent.steps.requests`) Defines a single step in a plan. Contains `plan_id`, `step_id`, `step_index`, `step_type`, `instructions`, `parameters`.
    * **`StepResultEvent.v1`**: (Topic: `agent.steps.results`) Outcome of a step execution. Contains `step_id`, `status`, `output`, `error`, `metrics`.
* **Synchronous Calls**: Interactions with MemoryService and ProviderAdapterLayer are typically synchronous (e.g., gRPC) but also have defined schemas for audit/replay.

*(Refer to PDF pages 45-51 for detailed JSON schemas and message flow table.)*

## 5. Error Handling Strategy

A robust error handling strategy is crucial for system resilience.
* **General Principles**: Standardization (consistent error structures), comprehensive logging (structlog with `trace_id`), clear user feedback, fail fast where appropriate, and idempotency for event handlers.
* **Error Types & Handling**:
    * **Transient Errors** (network issues, rate limits): Automatic retries with exponential backoff (in ProviderAdapterLayer, MemoryService, Iggy Integration).
    * **Persistent External Failures** (invalid API keys, DB down): Circuit breakers (in client components).
    * **Configuration Errors**: Validate on startup; fatal errors prevent service start.
    * **Planning & Step Execution Errors**: Reported via `StepResultEvent`; plan repair/retries; step-level retries; potential for compensation (Saga pattern - future enhancement).
    * **Memory Service Errors**: Internal retries/circuit breakers; may use cache.
    * **Iggy Communication/Messaging Errors**: Retries, circuit breakers; deserialization/processing failures routed to Dead Letter Queues (DLQs).
    * **Validation Errors**: Reject early with clear error messages (e.g., HTTP 400/422).
* **Observability**: All error handling logged; key error metrics exposed; alerts configured for critical errors and SLO violations.

## 6. Security Considerations

Security is a paramount concern and is addressed through multiple layers:
* **Authentication & Authorization**:
    * API Layer: OAuth 2.1 (JWT Bearer tokens) primary; API Keys for trusted service-to-service.
    * Authorization: Initial focus on principal-based resource access.
* **Data Security**:
    * **In Transit**: TLS (ideally 1.3) for all external and internal service communication.
    * **At Rest**: Sensitive config via env vars/secrets manager (e.g., Vault); DB-level encryption; Iggy server-side encryption (AES-256-GCM).
    * **PII Handling**: Detection and redaction/masking mechanisms.
* **Infrastructure Security**: Network segmentation, least privilege, regular patching.
* **Personality Pack Security (CRITICAL)**:
    * **Tool Sandboxing**: Essential (e.g., Wasm, Firecracker MicroVMs) with restricted filesystem, network, and resource access.
    * Input validation and output sanitization for tools.
    * Pack vetting/scanning.
* **Provider Security**: Secure API key management; mindful of data sent to LLMs.
* **Iggy Security**: Strong client credentials, stream/topic permissions, TLS 1.3, server-side encryption, limited network exposure. Consider mTLS.
* **Secret Management**: `.env` for local dev (gitignored); secure injection (Kubernetes Secrets, Vault) in production. `ConfigLoader` resolves placeholders.
* **Threat Modeling & Auditing**: Regular threat modeling, audit logging, penetration testing.

## 7. Development Lifecycle and CI/CD

A robust CI/CD pipeline using Poetry for dependency management.
* **Pipeline Stages**:
    1.  Linting & Static Analysis (e.g., `black`, `ruff`, `mypy`).
    2.  Unit Testing (e.g., `pytest`, high coverage, mocks).
    3.  Dependency & Security Scanning (e.g., `pip-audit`, SAST, container scanning).
    4.  Integration Testing (with ephemeral dependencies like Iggy, DBs via Docker Compose or testcontainers) & Contract Testing (against schemas, compatibility checks).
    5.  Build & Packaging (container images).
    6.  Deployment Strategy (Canary, Blue/Green) with monitoring.
    7.  Post-Deployment Validation (smoke tests).
* **Local Development**: `poetry install`, `.env` for secrets, `poetry run ...`.

## 8. Disaster Recovery (DR) and Compliance

* **Disaster Recovery**:
    * Define RPO & RTO (Targets TBD).
    * Backup Strategy: Regular automated backups for MemoryService (Vector DB, Cache if persistent), Iggy log segments, configurations. Off-site storage.
    * Restore Procedures: Documented and tested.
    * High Availability (HA) measures to minimize DR invocation.
* **Compliance**:
    * Identify applicable standards (e.g., GDPR, HIPAA, SOC 2).
    * Secure audit logging.
    * Data governance policies (classification, retention, access, deletion).
    * Regular audits.

## 9. Scalability Strategy

Designed for horizontal scalability using stateless services and Apache Iggy.
* **Core Principle**: Stateless services (API, Core Runtime, Provider Adapters) process requests based on input/context from MemoryService or messages. Iggy decouples components for independent scaling.
* **Component-Specific Scaling**:
    * **API Layer**: Replicas behind load balancer. WebSockets may use sticky sessions or shared state backend (Redis Pub/Sub).
    * **Core Runtime**: Replicas; Iggy Consumer Groups distribute load. Idempotency is key.
    * **Memory Service**: Depends on backend (Vector DB: read replicas, partitioning; Cache: Redis Cluster/Sentinel).
    * **Apache Iggy Server**: Scales via partitioning and consumer scaling; clustering for bus HA/throughput.
* **Key Mechanisms**: Iggy Partitioning (by `session_id`/`user_id`), Iggy Consumer Groups, Autoscaling (Kubernetes HPA based on CPU/Memory/custom metrics like Iggy consumer lag).
* **Considerations**: Load testing is crucial to identify bottlenecks (slow tools, DB contention, Iggy partition hotspots).

## 10. Apache Iggy vs. Kafka Rationale

Apache Iggy was chosen over Kafka for several reasons:
* **Performance**: Rust-based efficiency (no GC spikes), high throughput, lower resource footprint.
* **Simplicity**: Single binary deployment (no Zookeeper), built-in admin tools, multiple transport protocols (TCP, QUIC, HTTP).
* **Feature Parity (Conceptual)**: Persistent append-only log, streams/topics/partitions, consumer groups.
* **Advanced Capabilities**: Built-in message deduplication, native data encryption.

### Iggy Configuration for Agent Shell (Conceptual)

* **Stream/Topic Structure Example**:
    ```
    agent-streams/
    ├── turns/ (partitions by tenant_id/session_id)
    │   ├── user-messages
    │   ├── agent-responses
    │   ├── plans
    │   └── steps
    ├── events/
    │   ├── lifecycle-events
    │   └── system-notifications
    ├── metrics/
    │   ├── latency
    │   ├── token-usage
    │   └── costs
    └── logs/
        ├── info
        ├── warning
        └── error
    ```
* **Python SDK Integration**: The official Iggy Python SDK is used for producing and consuming messages.

## 11. Deployment Architecture (Conceptual)

Containerized components deployed, potentially on Kubernetes, with Iggy as the central message bus.
```mermaid
graph TD
    subgraph Kubernetes Cluster
        direction LR
        APIService[API Service]
        CoreRuntime[Core Runtime]
        ProviderAdapters[Provider Adapters]
        MemoryService[Memory Service]
        ApacheIggy[Apache Iggy Cluster]
        Observability[Observability Stack]

        APIService --> ApacheIggy;
        CoreRuntime --> ApacheIggy;
        ProviderAdapters -.-> CoreRuntime;
        MemoryService -.-> CoreRuntime;
        CoreRuntime --> Observability;
        ApacheIggy --> Observability;
    end
For production, Iggy's clustering and replication capabilities will be leveraged for high availability.12. ConclusionThis architecture provides a modern, efficient, and scalable foundation for the KFM Agent Shell project, meeting the requirements outlined in the PRD by leveraging Apache Iggy and sound design principles.13. Next Steps (from original document)Component Specification: Detail the interfaces and classes for each component.Iggy Integration Proof-of-Concept: Develop a small POC to validate Ig