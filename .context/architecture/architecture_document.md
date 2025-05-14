# Agent Shell Architecture Design with Apache Iggy Integration

Before diving into the detailed architecture, this report outlines a comprehensive design for the Agent Shell project as specified in the PRD, with Apache Iggy integrated as the message streaming backbone. The architecture emphasizes modularity, provider agnosticism, and high performance while leveraging Iggy's capabilities to replace a traditional Kafka-based message bus.

## Architecture Overview

The Agent Shell architecture follows a modular, event-driven approach with Apache Iggy serving as the central nervous system for asynchronous communication between components. This design supports the PRD's requirements for provider agnosticism, personality modularity, and observability.

### Core Architecture Principles

- **Decoupled Components**: Each architectural component operates independently, communicating via well-defined interfaces[2]
- **Event-Driven Communication**: Async event streams via Apache Iggy enable loose coupling[5]
- **Provider Abstraction**: Uniform interfaces to multiple LLM vendors[2]
- **Personality Modularity**: Self-contained personality packs that can be hot-loaded[2]
- **Observability First**: Comprehensive metrics and logging throughout the system[2]
- **Scalable Design**: Horizontal scaling through stateless components and Iggy's partitioning[5][6]

## Component Architecture

### Core Runtime Layer (Detailed Design)

The Core Runtime Layer serves as the central orchestrator for the Agent Shell, managing the end-to-end "Turn → Plan → Step" workflow. It receives user input, coordinates with various services (LLM providers via Provider Adapter Layer, Memory Service, Personality Pack Manager), and directs the generation of an agent response. This layer is designed to be stateless where possible, relying on Apache Iggy for event-driven communication and state progression, and the Memory Service for persistent context.

```mermaid
graph TD
    subgraph Core Runtime Layer
        TM[TurnManager<br/>- Turn Lifecycle<br/>- Personality Sel<br/>- Context Init]
        PE[PlanExecutor<br/>- Plan Generation<br/>- LLM Prompting<br/>- Plan Validation]
        SP[StepProcessor<br/>- Step Execution<br/>- State Updates]
        CM[ContextManager<br/>- Session State<br/>- Memory Bridge]
        CL[ConfigLoader<br/>- Config Loading<br/>- Env Variables]
        EPS[EventPublisherSubscriber<br/>- Iggy Client Wrapper<br/>- Event Routing]

        TM --> PE
        PE --> SP
        TM -.-> CM
        PE -.-> CM
        SP -.-> CM
        TM -.-> EPS
        PE -.-> EPS
        SP -.-> EPS
        style TM fill:#f9f,stroke:#333,stroke-width:2px
        style PE fill:#f9f,stroke:#333,stroke-width:2px
        style SP fill:#f9f,stroke:#333,stroke-width:2px
        style CM fill:#ccf,stroke:#333,stroke-width:2px
        style CL fill:#ccf,stroke:#333,stroke-width:2px
        style EPS fill:#ccf,stroke:#333,stroke-width:2px
    end

    API[API Layer] --> TM
    CM -->|Session Data| MS[Memory Service]
    SP -->|LLM Calls, Tools| PAL[Provider Adapter Layer]
    SP -->|LLM Calls, Tools| PPM[Personality Pack Manager]
    EPS -->|Async Events| IGGY[Apache Iggy]
    
    linkStyle 0 stroke-width:2px,fill:none,stroke:black;
    linkStyle 1 stroke-width:2px,fill:none,stroke:blue;
    linkStyle 2 stroke-width:2px,fill:none,stroke:green;
    linkStyle 3 stroke-width:2px,fill:none,stroke:green;
    linkStyle 4 stroke-width:2px,fill:none,stroke:red;
```

#### Sub-Modules and Responsibilities

1.  **`ConfigLoader`**:
    *   **Responsibilities**:
        *   Loads, validates, and provides access to the primary system configuration from `config.toml`.
        *   **Typed Access**: Parses the TOML configuration into strongly-typed objects (e.g., using Pydantic models) ensuring settings are accessed type-safely by other components.
        *   **Secrets Management**: Securely loads sensitive values (API keys, passwords) referenced in `config.toml`. It resolves placeholders (e.g., `api_key = "${OPENAI_API_KEY}"`) by reading the corresponding environment variables. Direct loading from a dedicated secrets manager could be a future enhancement.
        *   **Configuration Provider**: Makes the validated, typed configuration available to other components (e.g., via dependency injection or a shared instance).
        *   **Hot-Reloading**: Optionally monitors `config.toml` for changes (using file system events). Upon detecting a change, it reloads and validates the configuration. If successful, it atomically updates the active configuration and emits a `ConfigurationChanged` event (e.g., via `EventPublisherSubscriber`) to notify interested components.
        *   **Baseline Configuration**: Provides the base system configuration, including default provider settings. It does *not* directly handle personality-specific overrides; these are defined in the personality `manifest.yaml` and applied by components like `TurnManager` or `ProviderAdapterLayer` when processing a turn with a specific personality.
    *   **Failure Behavior**: On initial load failure (parsing error, validation error, missing required env var), the service MUST fail to start. For hot-reloading failures, logs the error and continues using the last known good configuration; emits a `ConfigurationReloadFailed` event.
    *   **Key Interactions**: All components requiring configuration, `EventPublisherSubscriber` (for hot-reload events).

2.  **`TurnManager`**:
    *   **Responsibilities**:
        *   Manages the lifecycle of a single user interaction "turn," from receiving initial input (e.g., as a `TurnEvent` from the API Layer via Iggy) to the final agent response.
        *   Attaches a unique `trace_id` to each turn for observability.
        *   Coordinates with the `PersonalityPackManager` to select and load the appropriate `PersonalityInstance` based on configuration or user request.
        *   Initializes the turn context by interacting with the `ContextManager` to load session state and conversation history.
        *   Orchestrates the creation of an execution plan by invoking the `PlanExecutor`.
        *   Ensures turns are handled as atomic units with appropriate transaction-like semantics for state updates where applicable.
    *   **Key Interactions**: API Layer (indirectly via Iggy), `PlanExecutor`, `PersonalityPackManager`, `ContextManager`, `EventPublisherSubscriber`.
    *   **Consumes (Example Iggy Topic)**: `agent.turns.requests`
    *   **Produces (Example Internal Message/Event)**: `PlanRequest` to `PlanExecutor`.
    *   **Failure Behavior**: Responds with an error (e.g., HTTP 422) if a turn request is malformed or critical setup fails.

3.  **`PlanExecutor`**:
    *   **Responsibilities**:
        *   Receives a `PlanRequest` (containing user input, personality, and context) from the `TurnManager`.
        *   Generates a structured execution plan (e.g., a Directed Acyclic Graph - DAG of steps, or a linear sequence) to address the user's request. This may involve:
            *   Constructing appropriate prompts for an LLM, incorporating the selected personality's system instructions, user input, and relevant context from `ContextManager`.
            *   Making a call to an LLM via the `ProviderAdapterLayer` to generate the plan.
            *   Alternatively, using a rules-based engine or a predefined template for simpler tasks.
        *   Validates the generated plan against a schema or a set of predefined rules.
        *   Breaks the plan down into discrete, executable `Step` descriptors.
        *   Handles plan generation failures, potentially retrying with different strategies or repairing the plan.
    *   **Key Interactions**: `TurnManager`, `StepProcessor`, `ProviderAdapterLayer`, `ContextManager`, `EventPublisherSubscriber`.
    *   **Produces (Example Iggy Topic)**: `StepEvents` to `agent.steps.requests`.
    *   **Failure Behavior**: May skip a problematic part of a plan or log an error and halt the turn if a valid plan cannot be generated after retries.

4.  **`StepProcessor`**:
    *   **Responsibilities**:
        *   Consumes `StepEvents` (or `StepResult` events that trigger next steps) from Iggy, corresponding to individual steps in the execution plan.
        *   Executes each step sequentially or with controlled parallelism if the plan allows and configuration enables it. **Note:** Enabling parallel execution (`core_runtime.feature_flags.enable_parallel_step_execution`) requires careful design of step dependency management within the plan (DAG scheduling), ensuring lock-free or properly synchronized updates to shared context via `ContextManager`, and guaranteeing that tool/LLM calls are safe for concurrent execution and side effects are idempotent or correctly managed.
        *   Step types include:
            *   LLM calls (via `ProviderAdapterLayer`).
            *   Tool invocations (from the active `PersonalityInstance`, interacting with `PersonalityPackManager` if tools are external).
            *   Memory operations (reading/writing via `ContextManager` / `MemoryService`).
            *   External API calls (if defined by a personality's tool).
        *   Manages the state of step execution, updating the turn's context via `ContextManager`.
        *   Handles streaming of partial results or responses back to the API Layer (e.g., via WebSockets) if a step produces them.
        *   Implements failure handling for individual steps, including retries or fallback mechanisms, potentially utilizing a circuit breaker pattern for repeated provider errors.
        *   **Security**: As noted in Security Considerations, inputs passed to tools (`arguments`) and outputs returned should be treated carefully (validation/sanitization may be needed depending on the tool and its usage).
        *   **Compensating Actions**: The `StepProcessor` should identify failed steps that require compensation (e.g., reversing a database write performed by a tool in a preceding step). This requires defining compensating actions within the tool/step definition or a separate registry. The `PlanExecutor` might need to incorporate compensation steps into the plan upon detecting certain failure modes reported by `StepResultEvent`. Further design is needed for robust compensation logic (e.g., Saga pattern).
    *   **Key Interactions**: `PlanExecutor` (receives plan structure), `ProviderAdapterLayer`, `PersonalityPackManager` (for tool execution), `MemoryService` (via `ContextManager`), `EventPublisherSubscriber`, API Layer (for streaming responses).
    *   **Consumes (Example Iggy Topic)**: `agent.steps.requests`, `agent.steps.results` (for chained steps).
    *   **Produces (Example Iggy Topic)**: `StepResultEvents` to `agent.steps.results`, `AuditEvent` for observability, response chunks to API layer.

    *   **Tool Execution Details**:
        *   When a `StepEvent` with `step_type: TOOL_CALL` is received, the `StepProcessor` retrieves the currently active `PersonalityInstance` for the turn (obtained originally by `TurnManager` from `PersonalityPackManager`).
        *   The `StepEvent.parameters` are expected to contain the `tool_name` and necessary `arguments` for the tool.
        *   The `StepProcessor` calls a method on the `PersonalityInstance` (e.g., `instance.get_tool(tool_name)`) to get the actual tool function/method object.
        *   If the tool is found, the `StepProcessor` invokes the tool function, passing the `arguments` from the step parameters. Tools are expected to be `async` functions.
        *   **Context Injection**: Tools may require access to runtime context (e.g., configuration, memory access, other tools). This context should be explicitly passed by the `StepProcessor` to the tool function, potentially via a dedicated `ToolContext` object containing interfaces to necessary services (e.g., a scoped `MemoryService` interface, config access), rather than allowing tools direct access to the full `StepProcessor` or `CoreRuntime` state.
        *   **Execution and Error Handling**: The `StepProcessor` `await`s the tool's execution.
            *   If the tool completes successfully, its return value is captured as the `output` in the `StepResultEvent`.
            *   If the tool raises an exception, the `StepProcessor` catches it, logs the error (with stack trace), and populates the `error` field in the `StepResultEvent` (e.g., `kind: 'ToolExecutionError'`, `detail: str(exception)`).
            *   Standardized exceptions defined within the framework might be used by tools to signal specific failure modes (e.g., `ToolInputError`, `ToolConfigurationError`).
        *   **Security**: As noted in Security Considerations, inputs passed to tools (`arguments`) and outputs returned should be treated carefully (validation/sanitization may be needed depending on the tool and its usage).
        *   **Compensating Actions**: The `StepProcessor` should identify failed steps that require compensation (e.g., reversing a database write performed by a tool in a preceding step). This requires defining compensating actions within the tool/step definition or a separate registry. The `PlanExecutor` might need to incorporate compensation steps into the plan upon detecting certain failure modes reported by `StepResultEvent`. Further design is needed for robust compensation logic (e.g., Saga pattern).

5.  **`ContextManager`**:
    *   **Responsibilities**:
        *   Manages the in-memory state for the current active turn (e.g., conversation history for the current interaction, intermediate data from steps).
        *   Acts as a bridge to the `MemoryService` for retrieving and persisting long-term user context, including:
            *   Full conversation history.
            *   User preferences.
            *   Session-specific information.
        *   Provides relevant context (scoped appropriately) to the `PlanExecutor` for prompt construction and to the `StepProcessor` for tool execution.
        *   Offers a short-term caching capability for frequently accessed session data to reduce latency to the `MemoryService`.
        *   **State Consistency & Transactions**: Ensuring atomic updates across multiple steps or involving both `ContextManager` and external systems (tools, LLM state) is challenging. Strategies include:
            *   **Optimistic Locking**: Using version numbers or timestamps when updating shared state in `MemoryService`, potentially combined with Redis WATCH/MULTI for cached state as suggested in reviews. Conflicts require retry or failure handling.
            *   **Event Sourcing**: Persisting state changes as a sequence of events. Rebuilding current state involves replaying events. This can simplify some consistency issues but adds complexity elsewhere.
            *   **Compensating Transactions (Saga Pattern)**: As mentioned under `StepProcessor`, define compensating actions for steps that succeed but whose overall transaction fails later. This requires careful design of reversal logic.
            *   **Chosen Strategy**: The initial implementation will likely focus on **idempotency and optimistic locking** for state managed within `MemoryService`/`ContextManager`. Full distributed transactionality or complex Saga implementations will be considered for future iterations if needed.
    *   **Key Interactions**: `TurnManager`, `PlanExecutor`, `StepProcessor`, `MemoryService`.
    *   **Failure Behavior**: Retries operations with the `MemoryService`; may proceed with stale data (if permissible and available from cache) or signal an error if critical context cannot be accessed.

6.  **`EventPublisherSubscriber`**:
    *   **Responsibilities**:
        *   Serves as a thin, robust wrapper around the Apache Iggy Python client.
        *   Handles publishing of all internal and external events generated by the Core Runtime to the appropriate Iggy streams and topics (e.g., turn lifecycle events, plan details, step executions, audit trails).
        *   Manages subscriptions to necessary Iggy streams, ensuring at-least-once message delivery semantics where required.
        *   Serializes outgoing messages and deserializes incoming messages.
        *   Implements standardized error handling and logging for Iggy interactions.
        *   Facilitates asynchronous processing patterns and decoupling between Core Runtime sub-modules and other system components.
        *   Ensures idempotent writes to Iggy where possible (e.g., using unique `step_id` or `event_id` as message keys or within payloads).
    *   **Key Interactions**: All Core Runtime sub-modules that produce or consume events, Apache Iggy Integration layer (uses its client).

### Structured Logging System
The Core Runtime Layer and other components utilize `structlog` for standardized, structured JSON logging. This approach enhances observability and simplifies log analysis and correlation.

Key features:
- **JSON Output**: Logs are rendered as JSON objects, making them easily parseable by log management systems.
- **Trace ID Injection**: A custom `structlog` processor (`add_trace_id` in `core/logging_config.py`) automatically injects a `trace_id` into every log entry, facilitating distributed tracing and request correlation. This `trace_id` typically originates from the initial request or is generated at the start of a turn.
  ```python
  # Example from core/logging_config.py
  # def add_trace_id(logger, method_name, event_dict):
  #     # Logic to retrieve or generate trace_id
  #     event_dict["trace_id"] = current_trace_id
  #     return event_dict
  
  structlog.configure(
      processors=[
          # ... other processors
          add_trace_id, # Ensure trace_id is added
          structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
      ],
      logger_factory=structlog.stdlib.LoggerFactory(),
      wrapper_class=structlog.stdlib.BoundLogger,
      cache_logger_on_first_use=True,
  )
  ```
- **Standard Library Deprecation**: Direct usage of Python's standard `logging` module is discouraged in favor of `structlog` to maintain consistency, except for very early bootstrap phases (like in `core/config.py`'s `config_logger`) before `structlog` is fully configured, or in third-party libraries.
- **Contextual Information**: `structlog` allows for easy binding of contextual information (e.g., `turn_id`, `step_id`) to loggers, enriching log entries.

### Metrics Collection
The Core Runtime is instrumented to collect and expose key operational metrics via Prometheus. These metrics provide insights into performance, usage, and potential issues. The primary metrics are defined in `core/metrics.py` and recorded at relevant points in the `TurnManager` and `StepProcessor`.

Key metrics include:
| Metric Name             | Type      | Description                                                                 | Labels                                 |
|-------------------------|-----------|-----------------------------------------------------------------------------|----------------------------------------|
| `LLM_REQUEST_LATENCY`   | Histogram | Latency of requests to LLM providers (e.g., OpenAI, Anthropic).             | `provider_name`, `model_name`          |
| `LLM_TOKENS_TOTAL`      | Counter   | Total number of tokens processed (input and output) by LLM providers.       | `provider_name`, `model_name`, `type` (prompt/completion) |
| `LLM_COST_TOTAL`        | Counter   | Estimated cost of LLM API calls in USD.                                     | `provider_name`, `model_name`          |
| `LLM_ERRORS_TOTAL`      | Counter   | Total number of errors encountered during LLM requests.                     | `provider_name`, `model_name`, `error_type` |
| `STEP_EXECUTION_TOTAL`  | Counter   | Total number of steps executed by the `StepProcessor`.                      | `step_type`, `status` (e.g., success/failure) |
| `TURN_EXECUTION_TOTAL`  | Counter   | Total number of turns processed by the `TurnManager`.                       | `status` (e.g., started/completed/failed) |
| `ACTIVE_TURNS`          | Gauge     | Number of turns currently being actively processed.                         |                                        |

These metrics are exposed via a `/metrics` endpoint (typically managed by `prometheus-fastapi-instrumentator` in `server.py`) for Prometheus to scrape.

#### Turn → Plan → Step Workflow

The Core Runtime implements the central workflow pattern that defines the Agent Shell's operation:

1.  **Turn Initiation**:
    *   User input is received by the **API Layer**, which may publish a `TurnEvent` to an Iggy topic (e.g., `agent.turns.requests`).
    *   The **`TurnManager`** consumes this event. It creates a new Turn context with a unique ID (`turn_id`, `trace_id`).
    *   The appropriate **`PersonalityInstance`** is selected (using `PersonalityPackManager`) based on the request or defaults from `ConfigLoader`.
    *   Initial context (conversation history, user preferences) is loaded from the **`MemoryService`** via the **`ContextManager`**.

2.  **Plan Generation**:
    *   The **`TurnManager`** sends an internal request or event to the **`PlanExecutor`**.
    *   The **`PlanExecutor`** constructs a detailed prompt. This prompt typically includes:
        *   The `PersonalityInstance`'s system instructions.
        *   The current user input.
        *   Relevant context (e.g., recent conversation history, user profile data from `ContextManager`).
    *   An LLM call is made via the **`ProviderAdapterLayer`** to generate a sequence of actions or a structured plan.
    *   The LLM's response is parsed into a structured `Plan` object (e.g., a list of `Step` objects).
    *   The `Plan` is validated. If invalid, retries or error handling occurs.
    *   The **`PlanExecutor`** then publishes `StepEvent` messages to an Iggy topic (e.g., `agent.steps.requests`) for each step in the plan.

3.  **Step Execution**:
    *   The **`StepProcessor`** (or multiple instances if scaled) consumes `StepEvent` messages from Iggy.
    *   For each `Step`, the `StepProcessor` determines the action:
        *   **LLM Call**: Invokes the **`ProviderAdapterLayer`**.
        *   **Tool Invocation**: Executes a tool from the loaded **`PersonalityInstance`**.
        *   **Memory Operation**: Interacts with the **`MemoryService`** via the **`ContextManager`**.
        *   Other custom actions.
    *   Results of each step are collected and can update the `ContextManager`'s state for the turn.
    *   Partial results might be streamed to the client via the **API Layer** (e.g., WebSocket).
    *   The `StepProcessor` publishes `StepResultEvent` messages to an Iggy topic (e.g., `agent.steps.results`), which can trigger subsequent steps or signal completion.

4.  **Response Generation & Turn Completion**:
    *   Once all necessary steps in the plan are completed, the final user-facing response is assembled by the `StepProcessor` or `TurnManager` based on the accumulated results.
    *   This response is sent back to the user via the **API Layer**.
    *   The final turn state (updated context, conversation history) is persisted by the **`ContextManager`** to the **`MemoryService`**.
    *   The **`TurnManager`** (or `StepProcessor` for the final step) publishes a `TurnCompletedEvent` or `TurnFailedEvent` to an Iggy topic for observability and auditing.

#### Lifecycle Flow Diagram (Sequence)

```mermaid
sequenceDiagram
    autonumber
    participant API as API Layer/Gateway
    participant IG_TurnsReq as Iggy (agent.turns.requests)
    participant TM as TurnManager
    participant PM as PersonalityPackManager
    participant CM as ContextManager
    participant MS as MemoryService
    participant PE as PlanExecutor
    participant PAL as ProviderAdapterLayer
    participant IG_StepsReq as Iggy (agent.steps.requests)
    participant SP as StepProcessor
    participant Tools as PersonalityTools
    participant IG_StepsRes as Iggy (agent.steps.results)
    participant IG_Audit as Iggy (audit stream)

    API->>IG_TurnsReq: UserInputEvent
    IG_TurnsReq-->>TM: Consumes UserInputEvent
    TM->>PM: GetPersonalityInstance(id)
    PM-->>TM: PersonalityInstance
    TM->>CM: LoadContext(user_id, session_id)
    CM->>MS: FetchHistory()
    MS-->>CM: HistoryData
    CM-->>TM: TurnContext
    TM->>PE: CreatePlan(UserInput, Personality, TurnContext)
    PE->>PAL: GeneratePlanLLMCall(prompt)
    PAL-->>PE: LLMPlanResponse
    PE->>IG_StepsReq: Publish StepEvent(s)
    
    IG_StepsReq-->>SP: Consumes StepEvent
    alt LLM Step
        SP->>PAL: ExecuteLLMCall(step_details)
        PAL-->>SP: LLMStepResult
    else Tool Step
        SP->>Tools: ExecuteTool(step_details)
        Tools-->>SP: ToolStepResult
    else Memory Step
        SP->>CM: ExecuteMemoryOp(step_details)
        CM->>MS: CRUD Op
        MS-->>CM: OpResult
        CM-->>SP: MemoryStepResult
    end
    SP->>CM: UpdateTurnState(StepResult)
    SP->>IG_StepsRes: Publish StepResultEvent
    SP->>API: StreamPartialResponse(chunk)
    
    Note over SP, IG_Audit: Loop for all steps...
    
    IG_StepsRes-->>PE: (Optional) Consumes StepResult for plan update/next step logic
    
    TM->>CM: FinalizeContext()
    CM->>MS: SaveHistory()
    TM->>API: SendFinalResponse()
    TM->>IG_Audit: Publish TurnCompletedEvent
```

#### Interaction with Other Layers

*   **API and Interface Layer**: The Core Runtime receives initial user requests (often as events via Iggy from the API Layer) and sends final responses/streams partial responses back to it.
*   **Provider Adapter Layer**: Invoked by `PlanExecutor` (for plan generation) and `StepProcessor` (for LLM-based steps). The choice of provider/model can be determined by `ConfigLoader` defaults or personality-specific settings.
*   **Personality Pack Manager**: `TurnManager` interacts to fetch the `PersonalityInstance`. `StepProcessor` interacts with the `PersonalityInstance` to execute tools.
*   **Memory Service**: `ContextManager` is the primary bridge for all reads/writes of persistent user and conversation context. `StepProcessor` might also trigger explicit memory operation steps.
*   **Apache Iggy Integration**: The `EventPublisherSubscriber` uses the Iggy client provided by this layer. All significant state transitions and task handoffs within the Core Runtime and to/from other components are designed to be event-driven via Iggy.
*   **Observability Layer**: All sub-modules are expected to produce structured logs (JSON) with `trace_id` and other correlation IDs. `EventPublisherSubscriber` can expose metrics related to Iggy stream interactions (e.g., message rates, errors, consumer lag). Events published by the Core Runtime (turn, plan, step events) are fundamental inputs for tracing and monitoring.

#### Configuration (`config.toml` Example)

```toml
[core_runtime]
  # Default behavior configuration
  max_turn_duration_seconds = 120
  max_steps_per_plan = 25
  default_planning_provider = "openai" # Provider to use for plan generation if not specified by personality
  default_planning_model = "gpt-4o"

  # Failure handling and retries
  max_plan_generation_retries = 2
  max_step_execution_retries = 3 # For transient errors in steps

  # Default personality if none specified in request
  default_personality_id = "default_assistant_v1.0"
  default_personality_version = "latest" # or a specific version

  # Context and history management
  max_conversation_history_turns = 20 # Max turns to load from history for context
  max_context_tokens_for_llm = 8000 # Approximate token limit for context provided to LLMs

[core_runtime.feature_flags]
  enable_parallel_step_execution = false # If planning graph allows, can steps run in parallel?
  # enable_streaming_tool_output = true
```

#### Concurrency & Scaling Notes

*   **Stateless Components (Goal)**: Sub-modules like `TurnManager`, `PlanExecutor`, and `StepProcessor` are designed to be largely stateless, processing individual events or requests. All significant per-turn state should ideally reside in the `ContextManager` (short-term in-memory cache backed by `MemoryService`) or be passed via Iggy events. This allows multiple instances of these Core Runtime components to run in parallel (e.g., as Kubernetes pods).
*   **Scalability**: The system can scale by increasing the number of Core Runtime instances. Load balancing for consuming Iggy events is handled by Iggy's consumer group mechanism.
*   **Idempotency**: Critical event handlers (especially `StepProcessor`) should strive for idempotency, often using unique IDs within event payloads (e.g., `turn_id`, `plan_id`, `step_id`) **and potentially checking the state in `MemoryService` (e.g., last processed step ID for a turn) before executing actions** to prevent duplicate processing on retries or redeliveries.
*   **State Consistency & Transactions**: Ensuring atomic updates across multiple steps or involving both `ContextManager` and external systems (tools, LLM state) is challenging. Strategies include:
    *   **Optimistic Locking**: Using version numbers or timestamps when updating shared state in `MemoryService`, potentially combined with Redis WATCH/MULTI for cached state as suggested in reviews. Conflicts require retry or failure handling.
    *   **Event Sourcing**: Persisting state changes as a sequence of events. Rebuilding current state involves replaying events. This can simplify some consistency issues but adds complexity elsewhere.
    *   **Compensating Transactions (Saga Pattern)**: As mentioned under `StepProcessor`, define compensating actions for steps that succeed but whose overall transaction fails later. This requires careful design of reversal logic.
    *   **Chosen Strategy**: The initial implementation will likely focus on **idempotency and optimistic locking** for state managed within `MemoryService`/`ContextManager`. Full distributed transactionality or complex Saga implementations will be considered for future iterations if needed.
*   **Back-pressure**:
    *   Iggy consumer clients (via `EventPublisherSubscriber`) should handle back-pressure from the Iggy server.
    *   The `StepProcessor` might implement internal mechanisms to limit the number of concurrent in-flight steps it processes (e.g., via a semaphore or bounded queue) to avoid overwhelming downstream services (LLMs, tools) or its own resources.
    *   If streaming responses to clients (e.g., via WebSockets), the `StepProcessor` or API layer needs to manage buffer sizes and potentially pause consumption from Iggy if client connections are slow.

This detailed design for the Core Runtime Layer aims to provide a robust and scalable engine for the Agent Shell. **Ensuring robust state management, idempotency, and defining a clear strategy for parallel execution and compensation are key areas for implementation focus and testing.**

```mermaid
graph TD
    subgraph Provider Adapter Layer
        direction TB
        PF[ProviderFactory]
        PI(ProviderInterface ABC<br/>- async generate()<br/>- async embed()<br/>- async moderate())
        CA[ConcreteAdapters<br/>- OpenAIAdapter<br/>- AnthropicAdapter<br/>- GroqAdapter<br/>- ...]
        RH[RetryHandler]
        CT[CostTracker]
        EN[ErrorNormalizer]

        PI --> CA
        PF --> PI
        style PF fill:#f9f,stroke:#333,stroke-width:2px
        style PI fill:#f9f,stroke:#333,stroke-width:2px
        style CA fill:#ccf,stroke:#333,stroke-width:2px
        style RH fill:#ccf,stroke:#333,stroke-width:2px
        style CT fill:#ccf,stroke:#333,stroke-width:2px
        style EN fill:#ccf,stroke:#333,stroke-width:2px
    end

    CoreRuntime[Core Runtime] -->|Request structured LLM call| PF
    CA -->|Return standardized response/error| CoreRuntime
    CA -->|Native API calls| ExtAPI[External LLM APIs<br/>(OpenAI, Anthropic, etc.)]
    ExtAPI -->|Native API responses/errors| CA
    
    linkStyle 0 stroke-width:2px,fill:none,stroke:black;
    linkStyle 1 stroke-width:2px,fill:none,stroke:black;
    linkStyle 2 stroke-width:2px,fill:none,stroke:blue;
    linkStyle 3 stroke-width:2px,fill:none,stroke:blue;
```

**Responsibilities:**

*   **Abstraction:** Provide a single, consistent asynchronous interface for the Core Runtime to interact with any supported LLM provider.
*   **Adaptation:** Translate generic requests from the Core Runtime into provider-specific API calls and map provider-specific responses/errors back to a standardized format.
*   **Extensibility:** Allow new LLM providers to be added with minimal changes to the Core Runtime, typically by implementing a new adapter class.
*   **Resilience:** Implement retry mechanisms with exponential backoff for transient provider errors.
*   **Cost Tracking:** Monitor token usage (input and output) for each call and calculate estimated costs based on provider-specific pricing models.
*   **Error Normalization:** Convert diverse provider errors into a standardized set of error types or codes that the Core Runtime can understand and handle more generically.

**Key Sub-modules/Classes:**

1.  **`ProviderFactory`**:
    *   **Responsibilities**: Dynamically instantiates the correct provider adapter based on configuration (`config.toml` via `ConfigLoader`).
    *   Ensures that only one instance of each provider client (if stateful or expensive to create) is used or manages a pool of clients.
    *   **Method Example**: `get_adapter(provider_name: str) -> ProviderInterface`

2.  **`ProviderInterface` (Abstract Base Class - ABC)**:
    *   **Responsibilities**: Defines the contract that all concrete provider adapters must implement.
    *   **Methods (async)**:
        *   `async generate(prompt: str, model_config: dict, context: UserContext) -> LLMResponse`:
            *   `prompt`: The input prompt for the LLM.
            *   `model_config`: Provider-specific parameters (e.g., model name, temperature, max tokens, streaming flag).
            *   `context`: `UserContext` for potential use in logging or fine-tuning requests.
            *   Returns `LLMResponse` containing the generated text, token counts, cost, and any errors.
        *   `async embed(text_chunks: list[str], model_config: dict) -> EmbeddingResponse`:
            *   `text_chunks`: List of text strings to embed.
            *   `model_config`: Provider-specific parameters (e.g., embedding model name).
            *   Returns `EmbeddingResponse` containing embeddings, token counts, cost.
        *   `async moderate(text: str, model_config: dict) -> ModerationResponse`:
            *   `text`: Text to be moderated.
            *   `model_config`: Provider-specific parameters.
            *   Returns `ModerationResponse` with moderation flags/scores, token counts, cost.

3.  **`<<ConcreteAdapter>>` (e.g., `OpenAIAdapter`, `AnthropicAdapter`, `GroqAdapter`)**:
    *   **Responsibilities**: Implements `ProviderInterface` for a specific LLM vendor.
        *   Handles authentication with the provider (using API keys from `ConfigLoader` / `.env`).
        *   Constructs provider-specific API request payloads from the generic inputs.
        *   Invokes the provider's SDK or HTTP API (using `httpx` for direct calls).
        *   Parses the provider's response, extracting generated content, token counts, and other relevant metadata.
        *   Utilizes `RetryHandler`, `CostTracker`, and `ErrorNormalizer`.
    *   Each adapter will typically use the official Python SDK for the respective provider if available and suitable, or `httpx` for direct API calls.

4.  **`RetryHandler`**:
    *   **Responsibilities**: Implements retry logic (e.g., exponential backoff with jitter) for transient network errors or specific provider rate limit errors.
    *   Configurable (max retries, backoff factor) via `config.toml`.

5.  **`CostTracker`**:
    *   **Responsibilities**: Calculates estimated cost for each LLM call based on token counts and provider-specific pricing information (which may need to be maintained/updated).
    *   Provides data for the `llm_tokens_total` (including $ value) Prometheus metric.
    *   **Rate Limit Handling**: Must correctly interpret rate limit responses (e.g., 429 errors) from providers and surface this information (e.g., via specific exceptions or error codes in `LLMResponse`) so the `RetryHandler` and potentially the `PlanExecutor` can react appropriately (e.g., exponential backoff, selecting an alternative provider/model).
    *   **Budget Enforcement**: Should include logic (TBD) to check requests against predefined cost/token budgets (potentially per-tenant or per-user) before making the call, failing the request if the budget would be exceeded. Requires integration with a budget management component or configuration.
    *   **Connection Pooling**: For providers using HTTP/S or gRPC, the adapter should implement or leverage connection pooling (e.g., via `httpx.AsyncClient` for HTTP, or gRPC channel options) to reduce latency from connection setup overhead.

6.  **`ErrorNormalizer`**:
    *   **Responsibilities**: Maps provider-specific error codes/messages to a predefined set of standardized error types or codes that the Core Runtime can understand and handle more generically.

**Key Data Structures (Illustrative - to be returned by interface methods):**

*   **`LLMResponse`**:
    *   `text_content`: The generated text output from the LLM.
    *   `input_tokens`: Number of tokens in the input prompt.
    *   `output_tokens`: Number of tokens in the generated response.
    *   `total_tokens`: Sum of input and output tokens.
    *   `cost`: Estimated cost of the call.
    *   `model_used`: Specific model that handled the request.
    *   `finish_reason`: Reason the LLM stopped generating (e.g., `stop_sequence`, `length`).
    *   `is_error`: Boolean indicating if an error occurred.
    *   `error_details`: Standardized error information if `is_error` is true.
    *   `raw_provider_response` (optional): The original response from the provider for debugging.
*   **`EmbeddingResponse`**: Similar structure with `embeddings` list, token counts, cost.
*   **`ModerationResponse`**: Similar structure with `moderation_flags`, `scores`, token counts, cost.

**Configuration (`config.toml`):**

*   Each provider will have its own section, e.g., `[providers.openai]`.
*   Settings include: `api_key_env_var` (name of env var holding the key), default `model` for generate/embed, specific endpoint URLs if not using SDK defaults, retry configurations.
*   Example:
    ```toml
    [providers.openai]
    api_key_env_var = "OPENAI_API_KEY"
    default_model = "gpt-4o"
    # Potentially other OpenAI specific settings
    connection_pool_size = 20 # Example for HTTPX client
    # enable_http2 = true # Example for HTTPX client

    [providers.anthropic]
    api_key_env_var = "ANTHROPIC_API_KEY"
    default_model = "claude-3-opus-20240229"
    ```

**Interaction with Core Runtime:**

*   The `StepProcessor` in the Core Runtime, when needing an LLM operation, will:
    1.  Request the `ProviderFactory` for an adapter instance based on the `current_provider` from `config.toml` or a personality-specified provider.
    2.  Invoke the appropriate method (e.g., `generate()`) on the adapter instance.
    3.  Receive the standardized response (e.g., `LLMResponse`) or handle standardized errors.

This layer is critical for decoupling the core logic of the Agent Shell from the specifics of any individual LLM provider, making the system flexible and easier to maintain and extend with new AI capabilities. **Implementing robust rate limit handling, connection pooling, and cost budget enforcement are key operational considerations.**

### Personality Pack Manager

Manages the loading, validation, and runtime availability of personality packs. This component is key to achieving the PRD goal of modular and hot-loadable personalities.

```mermaid
graph TD
    subgraph Personality Pack Manager as PPM
        PL[Pack Loader]
        MPV[Manifest Parser & Validator]
        HRC[Hot-Reload Controller]
        PR[Pack Registry]
        PIF[PersonalityInstance Factory]

        PL --> MPV
        MPV --> PIF
        HRC --> PL
        HRC --> PR
        PIF --> PR

        style PL fill:#f9f,stroke:#333,stroke-width:2px
        style MPV fill:#f9f,stroke:#333,stroke-width:2px
        style HRC fill:#f9f,stroke:#333,stroke-width:2px
        style PR fill:#ccf,stroke:#333,stroke-width:2px
        style PIF fill:#ccf,stroke:#333,stroke-width:2px
    end

    CRT[Core Runtime (TurnManager)] -->|Request PersonalityInstance| PR
    PR -->|Return PersonalityInstance| CRT
    subgraph Filesystem
      direction TB
      PP[Personality Packs<br/>(e.g., personalities/)]
    end
    PPM -->|Scans, Loads| PP

    linkStyle 0 stroke-width:2px,fill:none,stroke:black;
    linkStyle 1 stroke-width:2px,fill:none,stroke:black;
    linkStyle 2 stroke-width:2px,fill:none,stroke:blue;
```

**Personality Pack Structure (Directory Layout Example):**

A personality pack is a directory containing all necessary files to define a specific agent personality. *Note: This example shows the pack structure itself, not the whole project.* See the Project Root structure below for the overall layout.

```
personalities/
└── example_personality_v1/
    ├── manifest.yaml
    ├── prompts/
    │   ├── system_prompt.md
    │   └── other_prompts.txt
    ├── tools/
    │   ├── __init__.py
    │   └── custom_tool.py
    └── knowledge/ (Optional: for RAG capabilities)
        ├── document1.txt
        └── data_source.csv
```

**Project Root Structure (Illustrative):**
```
KFM_Framework_Enablers/
├── .context/              # Aegis framework directory
├── .env                   # Local environment variables (gitignored)
├── .gitignore
├── LICENSE                # Added MIT License
├── README.md
├── cli.py
├── config.toml
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── context.py
│   ├── logging_config.py  # Added structlog configuration
│   ├── metrics.py         # Added Prometheus metrics definitions
│   └── runtime.py
├── design_doc/
├── memory/
├── personalities/
│   └── default/
├── providers/
│   ├── __init__.py
│   ├── factory.py
│   └── openai.py          # Anthropic, Groq adapters TBD
├── server.py
├── tests/
│   ├── __init__.py
│   ├── test_metrics.py    # Added metrics tests
│   └── memory/
├── pyproject.toml         # Poetry configuration
└── poetry.lock            # Poetry lock file
```

**`manifest.yaml` Details:**

This file is the entry point for a personality pack and defines its metadata and configuration.

```yaml
id: "example_personality_v1"       # Unique identifier for the personality pack
version: "1.0.2"                    # Semantic version for the pack
name: "Example Assistant"
description: "A helpful assistant that can perform custom actions."
author: "Agent Shell Team"
created_date: "2025-05-10"

# Default LLM provider and model settings for this personality
# Can be overridden by global config or user preferences
provider_settings:
  default_provider: "openai"        # e.g., openai, anthropic, groq
  default_model: "gpt-4o"
  # Specific parameters for this personality when using the default model
  model_parameters:
    temperature: 0.7
    max_tokens: 1500

# System prompt configuration
system_prompt:
  template_file: "prompts/system_prompt.md" # Path relative to pack root
  # Variables expected by the system prompt template (to be filled by Core Runtime)
  variables: ["user_name", "current_date"]

# Tool definitions
tools:
  enabled: true
  module: "tools"  # Python module name within the pack (e.g., tools/ for tools/__init__.py)
  # Optional: List specific functions/classes to expose if not all in module
  # exposed_tools: ["get_weather", "run_query"]

# Knowledge base configuration (for RAG)
knowledge:
  enabled: false
  # sources:
  #   - type: "file"
  #     path: "knowledge/document1.txt"
  #     loader: "text_loader" # Optional: specifies how to load the content
  #   - type: "directory"
  #     path: "knowledge/"
  #     loader: "directory_loader"
  # index_strategy: "local_faiss" # Optional: if specific indexing is needed
```

**Sub-Modules and Responsibilities:**

1.  **`PackLoader`**:
    *   **Responsibilities**:
        *   Scans a designated directory (e.g., `personalities/` defined in `config.toml`) for potential personality pack directories.
        *   Identifies packs based on the presence of a `manifest.yaml` file.
        *   Initiates the loading process for each discovered pack by passing it to the `ManifestParserValidator`.
    *   **Key Interactions**: `ManifestParserValidator`, Filesystem.

2.  **`ManifestParserValidator`**:
    *   **Responsibilities**:
        *   Parses the `manifest.yaml` file for a given pack.
        *   Validates the manifest content against a predefined schema (e.g., checks for required fields, correct data types).
        *   Verifies the existence of referenced files within the pack (e.g., prompt templates, tool modules, knowledge files).
        *   Performs basic validation of the `tools` module (e.g., attempts to import it to catch syntax errors). **Note:** This basic import check does not guarantee runtime safety or correctness of the tool code.
        *   If validation is successful, passes the parsed and validated manifest data to the `PersonalityInstanceFactory`.
    *   **Key Interactions**: `PersonalityInstanceFactory`, Filesystem.

3.  **`HotReloadController`**:
    *   **Responsibilities**:
        *   Monitors the personality packs directory for any changes (new packs added, existing packs modified or deleted) using a file system watcher (e.g., `watchdog`).
        *   When a change is detected:
            *   For new packs: Triggers the `PackLoader`.
            *   For modified packs: Invalidates the old version in the `PackRegistry` and triggers a reload (via `PackLoader` -> `ManifestParserValidator` -> `PersonalityInstanceFactory`). Manages versioning to ensure smooth transitions, **potentially keeping old instances active for ongoing turns if necessary (strategy TBD - requires careful handling of state and tool availability).**
            *   For deleted packs: Removes the personality from the `PackRegistry`.
        *   Ensures minimal disruption to ongoing operations during reloads.
    *   **Key Interactions**: `PackLoader`, `PackRegistry`, Filesystem.

4.  **`PackRegistry`**:
    *   **Responsibilities**:
        *   Maintains an in-memory registry of all currently valid and loaded `PersonalityInstance` objects, keyed by their `id` and `version`.
        *   Provides methods for the Core Runtime (specifically `TurnManager`) to:
            *   List available personalities.
            *   Retrieve a specific `PersonalityInstance` by ID (and optionally version).
            *   Retrieve the default personality.
    *   **Key Interactions**: `TurnManager`, `HotReloadController`, `PersonalityInstanceFactory`.

5.  **`PersonalityInstanceFactory`**:
    *   **Responsibilities**:
        *   Receives validated manifest data from the `ManifestParserValidator`.
        *   Constructs and returns a `PersonalityInstance` object.
        *   This involves:
            *   Loading and preparing prompt templates.
            *   Importing and preparing tool functions/classes from the specified tools module.
            *   If knowledge is enabled, initializing the knowledge base (e.g., loading documents, setting up a RAG retriever with the `MemoryService`).
    *   **Key Interactions**: `ManifestParserValidator`, `PackRegistry`, `MemoryService` (for knowledge).

**`PersonalityInstance` (Runtime Object):**

This object represents an active, loaded personality and is used by the Core Runtime during a turn. It is *not* a sub-module of the manager, but rather what the manager produces and registers.

*   **Attributes**:
    *   `id`: Personality ID.
    *   `version`: Personality version.
    *   `name`: Display name.
    *   `manifest_data`: The full parsed manifest for reference.
    *   `system_prompt_template`: Loaded system prompt content/template engine.
    *   `tools`: A collection or module of callable tool functions/classes.
    *   `knowledge_retriever` (optional): An interface to query the personality's specific knowledge base.
    *   `default_provider_settings`: Default LLM provider and model settings.
*   **Methods (Examples)**:
    *   `get_system_prompt(variables: dict) -> str`: Formats the system prompt with provided variables.
    *   `get_tool(name: str) -> Callable`: Retrieves a specific tool function.
    *   `list_tools() -> list[str]`: Lists available tool names.
    *   `async query_knowledge(query_text: str) -> list[KnowledgeFragment]` (if knowledge enabled).

**Interaction with Core Runtime:**

*   The `TurnManager`, at the beginning of a turn or when a personality switch is requested:
    1.  Queries the `PackRegistry` for the desired `PersonalityInstance` (either by ID or requesting the default).
    2.  The `PackRegistry` returns the `PersonalityInstance`.
    3.  The `TurnManager` then uses this instance throughout the turn:
        *   To get the system prompt for the `PlanExecutor`.
        *   The `PlanExecutor` and `StepProcessor` use it to access tools and potentially query the knowledge base.

**Further Considerations for Personality Packs:**

*   **Tool Security & Sandboxing**: Executing arbitrary Python code from `tools/` modules presents a significant security risk.
    *   **Mitigation Strategy (Required)**: Implement robust sandboxing. Options require investigation and prototyping:
        *   **WebAssembly (Wasm)**: Compile tool code (or a runtime capable of executing it) to Wasm and run using a secure Wasm runtime (e.g., Wasmtime, Wasmer) with restricted capabilities (e.g., no filesystem access unless explicitly granted).
        *   **MicroVMs (e.g., Firecracker)**: Run each tool invocation in a lightweight, isolated microVM with strict resource limits and network policies.
        *   **Process-based Sandboxing (e.g., `nsjail`, `bubblewrap`)**: Run tool code in isolated Linux namespaces with restricted syscalls and filesystem views.
        *   **eBPF**: Use eBPF for fine-grained syscall filtering and monitoring (complex to implement correctly).
    *   **Initial Approach**: Prioritize exploring **Wasm or MicroVMs** for stronger isolation guarantees compared to basic process sandboxing.
The chosen solution MUST prevent tools from accessing arbitrary system resources, network endpoints, or sensitive configuration unless explicitly permitted via the injected `ToolContext`.
*   **Packaging and Distribution**: Relying on filesystem directories complicates signing, verification, and atomic updates.
    *   **Future Enhancement**: Consider packaging personalities as OCI-compatible container images or similar signed archive formats. This would allow for better supply chain security (signing, scanning) and potentially simplify deployment and rollback.
*   **Version Skew during Hot-Reload**: If a turn is in progress when a personality pack is updated, the `TurnManager` or `StepProcessor` needs a clear strategy for handling potential inconsistencies (e.g., finish the turn with the old version, attempt a safe transition, or fail the turn). This requires further design.

This detailed structure for the Personality Pack Manager allows for a flexible and extensible system where new personalities with custom prompts, tools, and knowledge can be easily developed, deployed, and updated. **Addressing tool sandboxing and defining clear hot-reload semantics are critical for security and stability.**

### Memory Service

Provides persistent and temporary memory capabilities for the Agent Shell, supporting conversation history, user context, and Retrieval Augmented Generation (RAG) for personalities.

```mermaid
graph TD
    subgraph Memory Service
        MO[Memory Operations<br/>- Interface (ABC)<br/>- Context Storage<br/>- History Storage<br/>- Knowledge Indexing<br/>- RAG Querying]
        VSA[Vector Store Adapter<br/>- pgvector<br/>- Weaviate<br/>- ...]
        CL[Cache Layer<br/>- Session Cache<br/>- Knowledge Index Cache]
        TTL[TTL Manager]

        MO -- Orchestrates --> VSA
        MO -- Orchestrates --> CL
        CL -- Manages TTL --> TTL

        style MO fill:#f9f,stroke:#333,stroke-width:2px
        style VSA fill:#ccf,stroke:#333,stroke-width:2px
        style CL fill:#ccf,stroke:#333,stroke-width:2px
        style TTL fill:#ccf,stroke:#333,stroke-width:2px
    end

    CRT[Core Runtime (ContextManager, StepProcessor)] -->|CRUD operations, context, RAG queries| MO
    PPM[Personality Pack Manager (PersonalityInstanceFactory)] -->|RAG setup| MO
    VSA -->|DB interactions| VDB[(Vector DB<br/>Postgres/pgvector, etc.)]
    CL -->|Cache reads/writes| Cache[(Cache<br/>Redis)]

    linkStyle 0 stroke-width:2px,fill:none,stroke:black;
    linkStyle 1 stroke-width:2px,fill:none,stroke:black;
    linkStyle 2 stroke-width:2px,fill:none,stroke:blue;
    linkStyle 3 stroke-width:2px,fill:none,stroke:blue;
```

**Responsibilities:**

*   **Context Persistence**: Store and retrieve user-specific context, including conversation history, preferences, and session state.
*   **Knowledge Base Management**: For personalities with RAG capabilities, manage the indexing, storage, and retrieval of knowledge documents.
*   **Caching**: Provide a caching layer for frequently accessed data to improve performance.
*   **Data Abstraction**: Offer a consistent API for memory operations, abstracting the underlying storage technologies.

**Key Data Structures (Conceptual - managed by the service):**

*   **`UserSessionContext`**:
    *   `user_id`: Identifier for the user.
    *   `session_id`: Identifier for the session.
    *   `conversation_history`: List of `Message` objects (e.g., `{'role': 'user'/'assistant', 'content': '...', 'timestamp': ...}`).
    *   `user_preferences`: Dictionary of user-specific settings.
    *   `last_accessed`: Timestamp of the last interaction.
*   **`KnowledgeDocument`**:
    *   `document_id`: Unique ID for the document.
    *   `personality_id`: ID of the personality this document belongs to.
    *   `source_uri`: Original source of the document (e.g., file path, URL).
    *   `content`: Text content of the document.
    *   `chunks`: List of `DocumentChunk` objects.
    *   `metadata`: Dictionary of additional information.
*   **`DocumentChunk`**:
    *   `chunk_id`: Unique ID for the chunk.
    *   `document_id`: Parent document ID.
    *   `text`: Text content of the chunk.
    *   `embedding`: Vector embedding of the text (stored in vector DB).
    *   `metadata`: Chunk-specific metadata.
*   **`CachedItem`**:
    *   `key`: Cache key.
    *   `value`: Cached data.
    *   `ttl`: Time-to-live for the cache entry.

**Sub-Modules and Responsibilities:**

1.  **`MemoryOperations` (Interface & Orchestration)**:
    *   **Responsibilities**:
        *   Defines a high-level Abstract Base Class (ABC) for all memory operations (e.g., `save_context`, `get_context`, `add_document_to_knowledge`, `search_knowledge`).
        *   Orchestrates calls to the `VectorStoreAdapter` and `CacheLayer` to fulfill requests.
        *   Handles logic for combining cached data with persistent data, or updating the cache after writes.
        *   Provides methods for the `ContextManager` (Core Runtime) to manage session context and conversation history.
        *   Provides methods for the `StepProcessor` (Core Runtime) and `PersonalityInstance` to perform RAG queries against a personality's knowledge base.
        *   Provides methods for `PersonalityInstanceFactory` to initialize and index knowledge for a personality.
    *   **Key Interactions**: `VectorStoreAdapter`, `CacheLayer`, `Core Runtime (ContextManager, StepProcessor)`, `PersonalityInstanceFactory`.

2.  **`VectorStoreAdapter`**:
    *   **Responsibilities**:
        *   Provides a consistent interface for interacting with various vector database backends (e.g., Postgres with pgvector, Weaviate, FAISS, ChromaDB).
        *   Abstracts provider-specific SDKs and connection details.
        *   Handles storage and retrieval of `DocumentChunk` embeddings.
        *   Executes vector similarity searches for RAG queries.
        *   Manages schema and indexing within the vector database for different personalities' knowledge bases.
        *   Configured via `config.toml` to select the active vector DB provider and its connection parameters.
    *   **Concrete Implementations**: `PgVectorAdapter`, `WeaviateAdapter`, etc.
    *   **Key Interactions**: `MemoryOperations`, underlying vector database.

3.  **`CacheLayer`**:
    *   **Responsibilities**:
        *   Provides an interface for caching and retrieving data (e.g., using Redis).
        *   Caches frequently accessed `UserSessionContext` to reduce latency.
        *   Potentially caches results of expensive knowledge index queries or even pre-computed knowledge indexes for very active personalities (if applicable and size permits).
        *   Manages cache keys and expiration policies (interacting with `TTLManager`).
        *   Configured via `config.toml` for connection details (e.g., Redis host, port).
    *   **Key Interactions**: `MemoryOperations`, `TTLManager`, underlying cache store (e.g., Redis client).

4.  **`TTLManager` (Time-To-Live Manager)**:
    *   **Responsibilities**:
        *   Manages the time-to-live (TTL) for cached items and potentially for some types of persistent data (e.g., old session data that needs to be archived or deleted).
        *   Works with the `CacheLayer` to set and refresh TTLs for cached `UserSessionContext`.
        *   May have background processes for periodic cleanup of expired data in persistent stores if not handled automatically by the DB (less common for primary data, more for auxiliary caches/logs if stored in DB).
        *   TTL policies configurable via `config.toml` (e.g., `session_cache_ttl_seconds`).
    *   **Key Interactions**: `CacheLayer`, potentially `VectorStoreAdapter` if managing TTLs for specific indexed data.

**Configuration (`config.toml`):**

```toml
[memory]
# Primary vector store provider for RAG and long-term memory
vector_store_provider = "pgvector" # Options: "pgvector", "weaviate", "faiss_local", etc.

[memory.pgvector]
  host = "localhost"
  port = 5432
  user = "db_user"
  password_env_var = "DB_PASSWORD"
  database = "agent_shell_memory"
  # Other pgvector specific settings, like table names

[memory.weaviate]
  url = "http://localhost:8080"
  api_key_env_var = "WEAVIATE_API_KEY"

# Cache configuration
cache_provider = "redis" # Options: "redis", "in_memory" (for dev)

[memory.redis]
  host = "localhost"
  port = 6379
  # password_env_var = "REDIS_PASSWORD"
  # db = 0

# TTL Settings (in seconds)
session_context_cache_ttl = 3600  # 1 hour
conversation_history_max_age = 0 # 0 for unlimited, or specify duration like "30d"
```

**Interaction with Core Runtime and Personalities:**

*   **`ContextManager`**: Uses `MemoryOperations` to save/load `UserSessionContext` at the start and end of turns, or as needed. This primarily involves the cache, with write-through/write-back to the persistent store.
*   **`StepProcessor`** (when executing a `memory_read` or `memory_write` step): Directly calls `MemoryOperations` methods.
*   **`StepProcessor`** (when a personality's tool needs RAG): If a tool within a `PersonalityInstance` needs to query its knowledge base, it will call a method on the `PersonalityInstance` (e.g., `query_knowledge()`). This method, in turn, will use the `MemoryOperations` (specifically its RAG querying capabilities) to search the indexed knowledge associated with that personality.
*   **`PersonalityInstanceFactory`**: When a personality pack with `knowledge.enabled = true` is loaded, the factory uses `MemoryOperations` to:
    1.  Ensure a knowledge index/space is prepared for this personality in the vector store.
    2.  Load documents specified in the manifest (e.g., from `knowledge/` directory).
    3.  Process and chunk these documents.
    4.  Generate embeddings for the chunks (using the `ProviderAdapterLayer`).
    5.  Store these chunks and their embeddings in the vector store via the `VectorStoreAdapter`.

This Memory Service design aims for flexibility in choosing backend technologies for vector storage and caching, while providing a robust set of functionalities crucial for an advanced agentic system.

### Apache Iggy Integration

This component is responsible for the seamless integration of Apache Iggy as the central message streaming platform for the Agent Shell. It abstracts Iggy-specific details and provides a clear interface for other components to publish and consume events. This aligns with the architectural decision to use Iggy for its high performance, low latency, and resource efficiency. [Source: Apache Iggy GitHub](https://github.com/apache/iggy), [Source: Iggy Proposal - The Apache Software Foundation](https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal).

```mermaid
graph TD
    subgraph Apache Iggy Integration Layer
        CA[Client Abstraction<br/>- IggyClient Wrapper<br/>- Ser/Des<br/>- Connection Mgmt<br/>- Error Handling]
        STM[Stream & Topic Manager<br/>- Definitions<br/>- Partitioning<br/>- Retention]
        CGC[Consumer Group Coordinator<br/>- Group Mgmt<br/>- Offset Mgmt]

        style CA fill:#f9f,stroke:#333,stroke-width:2px
        style STM fill:#ccf,stroke:#333,stroke-width:2px
        style CGC fill:#ccf,stroke:#333,stroke-width:2px
    end

    CRT[Core Runtime (EventPublisherSubscriber)] -->|Publish/Subscribe events| CA
    Other[Other Components] -->|Publish/Subscribe specific streams| CA

    CA -->|Uses Iggy Python SDK| IggySDK[Iggy Python SDK]
    STM -->|Configures Server| IggyServer[(Apache Iggy Server<br/>TCP, QUIC, HTTP<br/>Streams: turns, events, etc.)]
    CGC -->|Manages Consumers on| IggyServer
    IggySDK --> IggyServer

    linkStyle 0 stroke-width:2px,fill:none,stroke:black;
    linkStyle 1 stroke-width:2px,fill:none,stroke:black;
    linkStyle 2 stroke-width:2px,fill:none,stroke:blue;
    linkStyle 3 stroke-width:2px,fill:none,stroke:blue;
    linkStyle 4 stroke-width:2px,fill:none,stroke:blue;
```

**Responsibilities:**

*   **Centralized Communication Hub**: Facilitate all asynchronous inter-component communication within Agent Shell using Iggy streams and topics.
*   **Abstraction of Iggy SDK**: Provide a simplified and consistent interface over the native Iggy Python SDK, making it easier for other components to interact with the message bus without needing deep knowledge of Iggy's specifics.
*   **Configuration Management**: Handle the configuration for connecting to the Iggy server, including transport protocols, addresses, and security settings.
*   **Stream and Topic Management**: Define and potentially manage the lifecycle (creation, configuration) of necessary Iggy streams and topics as per Agent Shell's needs (though initial setup might be manual or via Iggy CLI/UI).
*   **Reliable Messaging**: Ensure reliable message delivery patterns (e.g., at-least-once) where required, leveraging Iggy's persistence and consumer group features.

**Key Sub-modules/Areas:**

1.  **`Client Abstraction` (e.g., `IggyBrokerClient`)**:
    *   **Responsibilities**:
        *   Wraps the native Iggy Python SDK (e.g., `IggyClient`).
        *   Manages connection establishment and lifecycle to the Iggy server (handling retries, disconnects).
        *   Provides simplified `publish(stream_id, topic_id, messages, partitioning_key=None)` and `subscribe(stream_id, topic_id, consumer_group_id, callback)` methods.
        *   Handles serialization (e.g., to Protobuf/JSON) of outgoing messages and deserialization of incoming messages.
        *   Implements standardized error handling and logging for Iggy interactions.
        *   Configures transport protocol (TCP, QUIC, or HTTP as per `config.toml`) and security (TLS, authentication credentials from `ConfigLoader`). Iggy supports multiple transport protocols which can be chosen based on performance or network needs. [Source: Iggy Proposal - The Apache Software Foundation](https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal)
    *   **Key Interactions**: Uses Iggy Python SDK; used by `EventPublisherSubscriber` in Core Runtime and any other component needing to send/receive messages.

2.  **`Stream & Topic Manager`**:
    *   **Responsibilities**:
        *   Defines the canonical list of streams and topics used by Agent Shell (e.g., `turns`, `events`, `system_logs`, `metrics_data` as previously outlined).
        *   Specifies default configurations for these streams/topics: partitioning strategy (e.g., by `user_id`, `session_id`, or round-robin), number of partitions. **Note:** Further analysis is needed to define strategies for detecting and mitigating hot partitions.
        *   Manages **Retention Policies**: Configures message retention for each topic (e.g., time-based like "7d" or size-based like "10GB") as supported by Iggy. This is crucial for managing disk space and data lifecycle. [Source: Iggy Proposal - The Apache Software Foundation](https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal)
        *   May include utility functions to programmatically create/verify streams/topics on Iggy server startup if necessary, using Iggy\'s management capabilities (though often these are pre-configured).
    *   **Key Interactions**: `ClientAbstraction` (to apply configurations if done programmatically), `config.toml` (for definitions).

3.  **`Consumer Group Coordinator`**:
    *   **Responsibilities**:
        *   Manages the definition and registration of consumer groups for different services (e.g., `core_runtime_turn_processors`, `observability_log_ingestors`).
        *   Facilitates load balancing and parallel processing by allowing multiple instances of a service to subscribe to the same topic as part of a consumer group. Iggy ensures each message in a partition goes to one consumer in the group.
        *   Supports reliable consumption by leveraging Iggy's server-side offset management for consumer groups, ensuring messages are not lost and can be reprocessed upon consumer restart.
    *   **Key Interactions**: `ClientAbstraction` (when subscribing).

**Iggy Features Leveraged:**

*   **Streams, Topics, Partitions**: For logical separation of data flows and parallelism.
*   **Persistent Append-only Log**: Ensures messages are durably stored.
*   **Consumer Groups**: For scalable and resilient message processing by Agent Shell components.
*   **Message Polling**: Flexible options (offset, timestamp) used by the `ClientAbstraction`.
*   **Transport Protocols (TCP, QUIC, HTTP)**: Agent Shell will primarily use TCP or QUIC for backend inter-service communication for performance, configurable via `config.toml`. HTTP might be used for specific management or less performance-critical interactions if needed. [Source: Iggy Proposal - The Apache Software Foundation](https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal)
*   **Client SDKs**: The official Iggy Python SDK will be the primary library used. [Source: Iggy Proposal - The Apache Software Foundation](https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal)
*   **Security**: TLS for encrypted communication and Authentication (username/password or PATs) for secure access to the Iggy server will be configured and managed. Iggy also supports AES-256-GCM data encryption, which could be explored for highly sensitive message payloads if deemed necessary. [Source: Iggy Proposal - The Apache Software Foundation](https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal) **Note:** Specific TLS versions (e.g., 1.3) and cipher suites should be mandated. Client certificate authentication should be considered for producers.
*   **Observability**: While the Observability Layer is separate, this integration layer will ensure that the Iggy client facilitates the collection of relevant metrics (e.g., publish/subscribe rates, errors) that can be exposed. Iggy server itself provides Prometheus metrics and OpenTelemetry logs. [Source: Iggy Proposal - The Apache Software Foundation](https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal)

**High Availability and Clustering (Future Enhancement / Investigation Area):**

*   **Current State**: The current design assumes a single-node Iggy deployment or relies on basic external load balancing.
*   **Requirement**: For production environments requiring high availability and fault tolerance, leveraging Iggy\'s clustering and replication features is necessary.
*   **Considerations (Based on Iggy\'s evolving capabilities)**:
    *   **Replication Strategy**: Evaluate Iggy\'s replication mechanisms (e.g., based on Viewstamped Replication or Raft) once mature.
    *   **Topology**: Define the cluster topology (e.g., 3-node minimum), quorum requirements, and peer discovery mechanisms.
    *   **Failover**: Document the expected behavior during node failures, including partition leadership transfer times and potential data loss (RPO/RTO targets to be defined in DR section).
    *   **Upgrade Path**: Plan for rolling upgrades of the Iggy cluster.
*   **Recommendation**: Prototype and conduct chaos testing on a multi-node Iggy cluster setup early in the implementation phase to validate readiness and operational characteristics for production workloads.

**Schema Governance (To Be Implemented):**

*   **Requirement**: Robust schema management is critical for evolving the event-driven architecture without breaking consumers.
*   **Strategy**:
    *   **Schema Registry**: Implement or integrate a schema registry. This could range from a simple approach (e.g., storing versioned JSON schemas in Git or S3) to a dedicated registry service (e.g., Confluent Schema Registry if compatibility is feasible, or a custom solution). The registry will store schemas keyed by stream/topic and version (`spec_version` from the envelope).
    *   **Schema Validation**: Producers and consumers MUST validate messages against the registered schema for the specified `spec_version`. Consumers should be designed for backward compatibility (tolerant reader).
    *   **Compatibility Checks**: Integrate automated schema compatibility checks (backward, forward, full) into the CI/CD pipeline before deploying changes to producers or consumers.
    *   **Versioning**: Adhere strictly to semantic versioning for the `spec_version` in the event envelope payload.

**Dead Letter Queue (DLQ) Strategy (To Be Implemented):**

*   **Requirement**: A mechanism is needed to handle messages that consistently fail processing after retries, preventing them from blocking consumers indefinitely.
*   **Strategy**:
    *   **DLQ Topics**: For each primary Iggy topic subject to processing failures (e.g., `agent.steps.requests`), define a corresponding DLQ topic (e.g., `agent.steps.requests.dlq`).
    *   **Routing**: Configure consumers (e.g., `StepProcessor`) to publish a message to the corresponding DLQ topic after a configured number of processing attempts fail (e.g., 3 retries).
    *   **Metadata Enrichment**: Messages sent to the DLQ MUST be enriched with metadata about the failure (e.g., original topic, consumer group ID, timestamp of failure, error message, stack trace, number of retries).
    *   **Monitoring & Alerting**: Monitor DLQ topic sizes via the Observability Layer. Configure alerts when DLQ depth exceeds predefined thresholds.
    *   **Replay/Repair Workflow**: Define operational procedures (runbooks) for inspecting messages in the DLQ, diagnosing the root cause, repairing problematic messages (if possible), and potentially replaying them back into the original topic or a dedicated reprocessing topic. This may involve manual intervention or automated repair workers (e.g., K8s CronJob).

**Configuration (`config.toml`):**

```toml
[iggy_integration]
  # Connection details for the Iggy server
  address = "localhost" # Iggy server host
  # Ports for different protocols
  tcp_port = 8090
  quic_port = 8070
  http_port = 3000 # For management or HTTP-based clients

  # Preferred transport protocol for Agent Shell internal communication
  default_transport = "tcp" # Options: "tcp", "quic", "http"

  # Authentication details
  username = "agent_shell_user"
  password_env_var = "IGGY_AGENT_SHELL_PASSWORD" # Environment variable holding the password
  # Alternatively, use PATs if supported and preferred
  # personal_access_token_env_var = "IGGY_AGENT_SHELL_PAT"

  # TLS settings
  tls_enabled = true
  # tls_ca_cert_path = "/path/to/ca.crt" # Optional: Path to CA certificate if using custom CA
  # tls_client_cert_path = "/path/to/client.crt" # Optional: For client certificate authentication
  # tls_client_key_path = "/path/to/client.key"  # Optional: For client certificate authentication

  # Default stream and topic configurations (can be overridden per component)
  default_serialization_format = "json" # "json", "protobuf"

  [iggy_integration.stream_defaults]
    # Default configurations for streams if not specified elsewhere
    [iggy_integration.stream_defaults.turns]
      partitions = 3
      retention_policy = "7d" # e.g., 7 days, or size like "10GB"

    [iggy_integration.stream_defaults.events]
      partitions = 1
      retention_policy = "30d"
      # DLQ Configuration Example (apply per stream/topic as needed)
      # dlq_topic = "agent.events.dlq"
      # max_processing_retries = 3

  [iggy_integration.clustering] # Placeholder for future HA config
    # enabled = false
    # strategy = "raft" # Example
    # node_id = 1 # Example
    # peers = ["iggy-node-2:port", "iggy-node-3:port"] # Example

  [iggy_integration.schema_registry] # Placeholder for registry config
    # type = "git" # Example: git, s3, custom_http
    # url = "git@github.com:org/repo.git" # Example
    # path = "schemas/" # Example
```

**Interaction with Other Components:**

*   The `EventPublisherSubscriber` sub-module of the `Core Runtime` will be the primary user of the `ClientAbstraction` to send and receive messages related to turn processing, plans, steps, and agent responses.
*   Other components, like a future `ObservabilityService` or administrative tools, might also use the `ClientAbstraction` to publish/subscribe to dedicated streams (e.g., for logs or metrics aggregation if done via Iggy messages, though direct Prometheus scraping from Iggy server is also an option). **DLQ monitoring and management tools will also interact via this layer or dedicated APIs.**

This integration layer ensures that Agent Shell can effectively use Apache Iggy as its messaging backbone, benefiting from its performance and features while keeping the rest of the codebase decoupled from the specifics of the message bus implementation. **Addressing Schema Governance, DLQ management, and validating High Availability are critical next steps for production readiness.**

### API and Interface Layer

Provides external access to the Agent Shell's functionalities for users, developers, and other systems. This layer is designed to support various interaction patterns, including the Xenocomm SDK, Machine-to-Component Protocol (MCP), and facilitate Agent-to-Agent (A2A) communication where appropriate.

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
        FAS[FastAPI Server<br/>- REST APIs<br/>- Xenocomm HTTP]
        WSH[WebSocket Handler<br/>- Streaming I/O<br/>- Xenocomm Realtime]
        GRPCS[gRPC Server<br/>- MCP Endpoints<br/>- Xenocomm SDK Endpoints]
        CLII[CLI Interface<br/>- Dev/Admin Cmds]
        CrossCutting[Auth & Rate Limiting<br/>(Cross-cutting)]

        FAS --- CrossCutting
        WSH --- CrossCutting
        GRPCS --- CrossCutting
        CLII --- CrossCutting

        style FAS fill:#f9f,stroke:#333,stroke-width:2px
        style WSH fill:#f9f,stroke:#333,stroke-width:2px
        style GRPCS fill:#f9f,stroke:#333,stroke-width:2px
        style CLII fill:#f9f,stroke:#333,stroke-width:2px
        style CrossCutting fill:#ccf,stroke:#333,stroke-width:2px
    end

    User -->|HTTP/S, WebSocket| FAS
    User -->|HTTP/S, WebSocket| WSH
    SDK -->|SDK-defined protocols, gRPC| GRPCS
    SDK -->|SDK-defined protocols, HTTP| FAS
    CLIUser -->|Shell commands| CLII
    MCPClient -->|gRPC, other MCP| GRPCS

    FAS -->|Core Logic via Service Interfaces| Services[Core Runtime & Other Services]
    WSH -->|Core Logic via Service Interfaces| Services
    GRPCS -->|Core Logic via Service Interfaces| Services
    CLII -->|Core Logic via Service Interfaces| Services
```

**Responsibilities:**

*   **Expose Functionality**: Make Agent Shell capabilities available through well-defined interfaces.
*   **User Interaction**: Handle direct user interactions via CLI and potentially web UIs (served by FastAPI).
*   **Programmatic Access**: Provide robust APIs for programmatic integration by external systems and the Xenocomm SDK.
*   **Real-time Communication**: Support streaming and real-time updates where necessary (e.g., chat, agent status).
*   **Standardization**: Ensure consistent data formats and error handling across different interfaces.
*   **Security**: Implement authentication, authorization, and rate limiting to protect the system.

**Sub-Modules and Responsibilities:**

1.  **`FastAPI Server`**:
    *   **Responsibilities**:
        *   Serves standard RESTful APIs for managing Agent Shell resources (e.g., personalities, memory configurations, user settings).
        *   Provides endpoints for status monitoring and system health checks.
        *   May serve parts of the Xenocomm SDK that rely on HTTP/S for specific operations (e.g., authentication, configuration retrieval).
        *   Can host a web-based administrative UI.
    *   **Key Interactions**: Core Runtime (for data and operations), Authentication service, Rate Limiting service.

2.  **`WebSocket Handler`**:
    *   **Responsibilities**:
        *   Manages persistent WebSocket connections for real-time, bidirectional communication.
        *   Primary interface for interactive chat sessions with agents.
        *   Streams agent responses, logs, and status updates to connected clients.
        *   Crucial for the Xenocomm SDK's interactive and streaming functionalities.
        *   **Scaling Strategy**: To handle a large number of concurrent WebSocket connections, a strategy like **using a Redis Pub/Sub backplane** will be employed. Each API server instance handling WebSockets will subscribe to relevant channels on Redis. When an event needs to be broadcast to a specific user or session, the message is published to the appropriate Redis channel, and all subscribed server instances forward it to their connected clients. This decouples message broadcasting from direct server-to-server communication for WebSocket state. Other options include dedicated WebSocket gateways (e.g., Centrifugo) if direct Redis management becomes complex.
    *   **Key Interactions**: Core Runtime (TurnManager for chat, EventPublisherSubscriber for real-time events), Authentication service, Redis (for Pub/Sub scaling).

3.  **`gRPC Server`**:
    *   **Responsibilities**:
        *   Provides high-performance, strongly-typed, and schema-defined (Protobuf) APIs.
        *   Serves as a primary endpoint for the **Xenocomm SDK**, especially for operations requiring efficiency and strict contracts. **Note: All gRPC service definitions (`.proto` files) MUST be versioned and managed in a dedicated repository or directory within the project.**
        *   Exposes endpoints for **MCP (Machine-to-Component Protocol)**, allowing other trusted systems or components to interact with Agent Shell in a structured and efficient manner (e.g., for control plane operations, bulk data exchange, or specific inter-component RPCs if not handled internally). **MCP contract definitions (.proto or other formats) MUST also be versioned and managed.**
        *   Can facilitate direct, synchronous **A2A (Agent-to-Agent)** request/response interactions if needed, as a complement to the primary asynchronous A2A via Apache Iggy.
    *   **Key Interactions**: Core Runtime, Memory Service, Provider Adapter Layer (for SDK/MCP initiated actions), Authentication service, Rate Limiting service.

4.  **`CLI Interface`**:
    *   **Responsibilities**:
        *   Provides command-line tools for developers and administrators to manage and interact with the Agent Shell.
        *   Supports operations like starting/stopping the shell, managing personality packs, viewing logs, inspecting system status, and executing administrative commands.
        *   Typically interacts with the other API interfaces (FastAPI, gRPC) or directly with service layers for its operations.
        *   **Responsibilities**:
            *   Handles authentication of users and systems across all external interfaces (FastAPI, WebSockets, gRPC).
            *   Supports various authentication mechanisms (e.g., API keys, OAuth tokens, session cookies). **The primary mechanism for API access will be OAuth 2.1 with JWT bearer tokens. API Key authentication may be supported for specific service-to-service interactions.** Detailed flow diagrams and token introspection/validation logic to be documented separately.
        *   **Key Interactions**: All externally exposed API endpoints.

5.  **`Authentication Service` (Cross-cutting)**:
    *   **Responsibilities**:
        *   Handles authentication of users and systems across all external interfaces (FastAPI, WebSockets, gRPC).
        *   Supports various authentication mechanisms (e.g., API keys, OAuth tokens, session cookies).
        *   Integrates with user management if applicable.
    *   **Key Interactions**: All externally exposed API endpoints.

6.  **`Rate Limiting Service` (Cross-cutting)**:
    *   **Responsibilities**:
        *   Implements rate limiting policies to prevent abuse and ensure fair usage of the API resources.
        *   Configurable limits per user, IP, or API endpoint.
    *   **Key Interactions**: All externally exposed API endpoints.

**Middleware:**
- **`track_metrics_middleware` (FastAPI):** Applied in `server.py`, this middleware performs several key observability functions:
    - Binds the request's `trace_id` (either from incoming headers like `X-Trace-ID` or newly generated) to the `structlog` context for the duration of the request.
    - Adds `trace_id` and a unique `request_id` to response headers (`X-Trace-ID`, `X-Request-ID`) for client-side correlation.
    - Works in conjunction with `prometheus-fastapi-instrumentator` to ensure requests are correctly instrumented for baseline metrics (latency, count, errors).

**Xenocomm SDK Support:**

The API and Interface Layer is designed to comprehensively support the Xenocomm SDK. This involves:
*   Defining API contracts (e.g., OpenAPI specs for REST, **versioned .proto files for gRPC**, WebSocket message formats) that align with the SDK's requirements.
*   Ensuring data models used by the APIs are compatible with those expected or generated by the SDK.
*   Providing clear documentation and examples for SDK users to integrate with Agent Shell.

**MCP (Machine-to-Component Protocol) Considerations:**

MCP allows other trusted systems or components to interact directly and efficiently with Agent Shell's core functionalities. This is primarily facilitated by:
*   **gRPC Endpoints**: Offering low-latency, structured communication for control, configuration, or data exchange tasks, **with versioned .proto contract definitions.**
*   **Dedicated Iggy Topics (Alternative)**: For event-driven MCP interactions, specific Iggy streams/topics can be defined, with messages adhering to a pre-defined schema. The API layer might provide management endpoints for these schemas or configurations if needed.

**A2A (Agent-to-Agent) Communication:**

While the primary A2A communication is event-driven and asynchronous via Apache Iggy (managed by the Core Runtime and Iggy Integration Layer), the API and Interface Layer can support A2A in the following ways:
*   **Service Discovery**: If agents need to communicate directly outside of Iggy, this layer could provide discovery mechanisms (though this adds complexity and is generally less preferred than brokered communication).
*   **Synchronous A2A via gRPC**: For specific use cases where agents require immediate request/response interaction, the gRPC server can expose endpoints for such communication, adhering to defined service contracts.

This layer ensures that Agent Shell is accessible, manageable, and extensible, catering to a diverse set of users and integration scenarios, including sophisticated SDK-based interactions and system-level component communication.

### Observability Layer

Enables comprehensive monitoring, logging, tracing, and debugging of the Agent Shell system. This layer is designed to provide deep insights into system behavior and integrate with standard observability frameworks like Prometheus and Grafana, while also allowing data export for other systems.

```mermaid
graph TD
    subgraph Observability Layer
        SL[Structured Logger<br/>(structlog)]
        MC[Metrics Collector<br/>(Prometheus Exp.)]
        TM[Trace Manager<br/>(OpenTelemetry)]
        CT[Cost Tracker Data]

        style SL fill:#f9f,stroke:#333,stroke-width:2px
        style MC fill:#f9f,stroke:#333,stroke-width:2px
        style TM fill:#f9f,stroke:#333,stroke-width:2px
        style CT fill:#f9f,stroke:#333,stroke-width:2px
    end

    subgraph External Systems
        LogAgg[Log Aggregation<br/>(e.g., Loki, ELK)]
        Prom[Prometheus Server]
        TraceBE[Tracing Backend<br/>(e.g., Tempo, Jaeger)]
        Graf[Grafana<br/>(Dashboards, Alerts)]
        Health[Health Monitor]
        IggyStream[Alt. Export: Iggy Stream]
    end

    SL -->|Logs (JSON)| LogAgg
    MC -->|Metrics (/metrics)| Prom
    TM -->|Traces (OTLP)| TraceBE
    CT -->|Cost Data| Graf

    Prom --> Graf
    LogAgg --> Graf
    TraceBE --> Graf
    
    AgentShellComponents --> SL
    AgentShellComponents --> MC
    AgentShellComponents --> TM
    AgentShellComponents --> Health
    AgentShellComponents -.->|Optional Export| IggyStream

    style Graf fill:#ccf,stroke:#333,stroke-width:2px
```

**Responsibilities:**

*   **Data Collection**: Gather logs, metrics, traces, and cost data from all Agent Shell components.
*   **Data Standardization**: Ensure data is in a consistent and usable format (e.g., structured JSON logs, Prometheus exposition format for metrics, OpenTelemetry for traces).
*   **Data Exposure**: Make observability data accessible to monitoring and analysis tools.
*   **Health Monitoring**: Provide mechanisms to assess and report the health status of individual components and the overall system.
*   **Debugging & Analysis**: Facilitate troubleshooting, performance analysis, and understanding of system behavior.

**Key Sub-modules/Areas:**

1.  **`Structured Logger`**:
    *   **Responsibilities**:
        *   Ensures all Agent Shell components produce structured logs, primarily in **JSON format**.
        *   Logs must include rich context: timestamps, severity levels, component/module names, and crucial **correlation IDs** (e.g., `trace_id` from `core/logging_config.py`, `span_id` from Trace Manager; `turn_id`, `plan_id`, `step_id` from Core Runtime; `user_id`, `session_id`). The `trace_id` is automatically injected by a `structlog` processor.
        *   Facilitates log collection and forwarding to log aggregation platforms (e.g., Grafana Loki, ELK stack, or cloud-native logging services).
    *   **Implementation**: Each component uses `structlog`, configured via `core/logging_config.py`, for standardized structured JSON output. Logs are typically collected by an agent (e.g., Promtail) and forwarded.
    *   **Log Management**: A clear policy for log rotation, retention periods, and potential PII (Personally Identifiable Information) redaction MUST be defined and implemented as part of the deployment configuration and log aggregation setup. Requirements will depend on operational needs and compliance standards (e.g., GDPR).

2.  **`Metrics Collector`**:
    *   **Responsibilities**:
        *   Collects and exposes metrics from all components in the **Prometheus exposition format** via a `/metrics` HTTP endpoint in each component (typically managed by `prometheus-fastapi-instrumentator` in `server.py`).
        *   Defines and standardizes key metrics (as detailed in the Core Runtime -> Metrics Collection section and implemented in `core/metrics.py`), including:
            *   **System Metrics**: CPU, memory, disk I/O, network usage for each Agent Shell microservice/component.
            *   **Application Metrics**: API request rates, error rates, latencies (per endpoint, per component); queue sizes and processing times for internal tasks.
            *   **Iggy-Related Metrics**: For Agent Shell clients: message publish/consume rates, error rates, connection status. For the Iggy server itself: stream/topic/partition metrics, broker health (scraped directly from Iggy's Prometheus endpoint).
            *   **LLM Provider Metrics**: Number of calls, latency per call, token counts (input/output), error rates (per provider, per model) – sourced from `ProviderAdapterLayer` and recorded using functions in `core/metrics.py`.
            *   **Personality Metrics**: Usage frequency of personalities, execution counts and latencies of tools within personalities (Note: Tool-specific metrics are a potential future enhancement).
            *   **Cost Metrics**: Aggregated cost data (`LLM_COST_TOTAL`) sourced from `ProviderAdapterLayer` via `core/metrics.py`.
        *   **Implementation**: Components use Prometheus client libraries (e.g., `prometheus_client` for Python) and helper functions in `core/metrics.py` to instrument their code. `prometheus-fastapi-instrumentator` provides baseline FastAPI metrics and integration.
        *   **Dashboards and Alerting**: While Grafana is the visualization tool, specific dashboards and alert rules need to be defined:
            *   **Key Dashboards**: System Overview (component health, overall traffic), API Performance (latency, error rates per endpoint), Iggy Health (broker status, consumer lag, message rates), Core Runtime Performance (turn latency, step success rates, queue depths), LLM Provider Performance (latency, errors, token usage per provider/model), Cost Analysis.
            *   **Critical Alerts**: High API error rates (>X%), High turn/step failure rates (>Y%), Iggy consumer lag exceeding threshold (e.g., >10s), Iggy broker unavailability, Critical component health failures (e.g., DB connection errors, cache failures), DLQ depth exceeding threshold, **SLO Violations (e.g., p95 turn latency > Z seconds)**.

3.  **`Trace Manager`**:
    *   **Responsibilities**:
        *   Implements distributed tracing using **OpenTelemetry** standards.
        *   Ensures trace context (trace IDs, span IDs) is propagated across component boundaries, including asynchronous communication via Apache Iggy (by embedding context in message headers) and within log messages (via the `add_trace_id` `structlog` processor).
        *   Instruments key operations within each component to create spans, capturing latency and metadata.
        *   Exports trace data to compatible backends like Grafana Tempo, Jaeger, or cloud-native tracing services via OTLP (OpenTelemetry Protocol).
        *   **Sampling Strategy**: A trace sampling strategy MUST be defined (e.g., probabilistic sampling like 10%, tail-based sampling, or adaptive sampling) to manage the volume of trace data and associated costs, while ensuring critical or error paths are captured. The strategy should be configurable.
    *   **Implementation**: Components use OpenTelemetry SDKs for instrumentation and context propagation.

4.  **`Cost Tracker` Integration**: (This module is functionally part of `ProviderAdapterLayer` but its output is key for observability)
    *   **Responsibilities**: Provides detailed cost information for LLM API calls.
    *   **Observability Output**:
        *   Exposes cost-related metrics (e.g., `llm_total_cost_usd`, `llm_cost_per_token`) via the `Metrics Collector`.
        *   Includes cost details in structured logs for relevant turns or steps.

5.  **`Health Monitor`**:
    *   **Responsibilities**:
        *   Each Agent Shell component (microservice) exposes health check endpoints (e.g., `/health/live`, `/health/ready`) that report its status and dependencies.
        *   An aggregated health view can be constructed by querying individual component health endpoints or through metrics.
        *   Health status integrated into monitoring dashboards (Grafana) and potentially used by orchestration platforms (e.g., Kubernetes).

**Integration with Prometheus & Grafana:**

*   **Prometheus**: Configured to scrape the `/metrics` endpoints of all Agent Shell components and the Apache Iggy server itself. Prometheus stores these time-series metrics efficiently. [Source: Get started with Grafana and Prometheus](https://grafana.com/docs/grafana/latest/getting-started/get-started-grafana-prometheus/)
*   **Grafana**: Acts as the primary visualization and dashboarding tool.
    *   Connects to **Prometheus** as a data source for querying and displaying metrics.
    *   Connects to a **log aggregation system (e.g., Grafana Loki)**, which ingests the structured JSON logs from Agent Shell, for log exploration and correlation with metrics/traces using the shared `trace_id`.
    *   Connects to a **tracing backend (e.g., Grafana Tempo or Jaeger)** for visualizing distributed traces (linked via `trace_id`) and linking them to logs and metrics.
    *   Pre-built dashboards will be designed for key aspects of Agent Shell (overall system health, API performance, LLM provider interactions, Iggy message flow, cost analysis). Example Dashboard ID: 7843 (Illustrative).

**Support for Other Observability Frameworks (JSON / Streaming Data Service):**

To ensure broad compatibility and support for various observability setups:

*   **Structured JSON Logs**: As mentioned, logs are in JSON, making them easily ingestible by a wide array of log management and analysis tools beyond Loki/ELK (e.g., Splunk, Datadog, cloud provider logging services).
*   **Streaming Telemetry via Apache Iggy (Optional Push Model)**:
    *   For specific real-time telemetry needs or integration with systems that prefer a push model (instead of Prometheus's pull model), Agent Shell can be configured to publish critical events, select metrics, or health status updates to dedicated Apache Iggy streams.
    *   Messages on these streams will be structured (e.g., JSON), allowing external consumers or custom adapters to subscribe and forward this data to other observability platforms or data lakes.
    *   This provides an extensible mechanism for telemetry export without requiring direct integration with every possible framework.

This comprehensive Observability Layer will provide the necessary tools and data to operate, maintain, and scale the Agent Shell effectively, offering deep insights into its operational state and performance characteristics.

## Data Flow and Message Schemas

This section defines the primary message structures ("wire contracts") used for communication within the Agent Shell, particularly for events flowing through Apache Iggy. Adhering to these schemas ensures interoperability between components and facilitates testing, observability, and schema evolution. All examples are expressed as JSON Schema 2020-12.

### 1. Common Event Envelope

All asynchronous events exchanged via Apache Iggy share a common envelope structure. The specific details of an event are contained within the `payload` object. This approach allows individual payload schemas to be versioned independently (`spec_version`) without altering the fundamental envelope structure, simplifying consumer logic.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AgentShellEventEnvelope-v1",
  "type": "object",
  "required": [
    "event_id",
    "type",
    "spec_version",
    "timestamp",
    "trace_id",
    "payload"
  ],
  "properties": {
    "event_id":   { "type": "string", "description": "ULID/UUID – used for idempotency and identification" },
    "type":       { "type": "string", "description": "Concrete event type name (e.g., TurnEvent, StepEvent)" },
    "spec_version": { "type": "string", "pattern": "^1\\.\\d+\\.\\d+$", "description": "Semantic version of the payload schema" },
    "timestamp":  { "type": "string", "format": "date-time", "description": "ISO 8601 timestamp of event creation" },
    "trace_id":   { "type": "string", "description": "OpenTelemetry trace ID for distributed tracing. Sourced from structlog context, propagated from initial request or generated per turn." },
    "tenant_id":  { "type": "string", "description": "Optional tenant identifier" },
    "session_id": { "type": "string", "description": "Optional session identifier" },
    "payload":    { "type": "object", "description": "Type-specific payload, schema defined below" }
  }
}
```
*Note: Subsequent schemas define only the structure of the `payload` object.*

### 2. Turn Initiation — `TurnEvent` Payload

Represents a new user interaction received by the API Layer and sent to the `TurnManager`.

*   **Iggy Topic:** `agent.turns.requests`
*   **Producer:** API Layer
*   **Consumer:** `TurnManager` (Core Runtime)

**Payload Schema (`TurnEvent.v1`):**
```json
{
  "title": "TurnEvent.v1",
  "type": "object",
  "required": ["turn_id", "user_message", "personality_id"],
  "properties": {
    "turn_id":        { "type": "string", "description": "Unique ID for this specific turn" },
    "user_message":   {
      "type": "object",
      "required": ["role", "content"],
      "properties": {
        "role":    { "const": "user" },
        "content": { "type": "string", "description": "The user's input message" }
      }
    },
    "personality_id": { "type": "string", "description": "ID of the personality context to use" },
    "metadata":       { "type": "object", "additionalProperties": true, "description": "Optional key-value pairs for extra context" }
  }
}
```

### 3. Plan / Step Execution Events

These events manage the orchestration of tasks within a turn.

#### 3.1 `StepEvent` Payload (Request)

Represents a single step within a plan, published by the `PlanExecutor` for execution by a `StepProcessor`.

*   **Iggy Topic:** `agent.steps.requests`
*   **Producer:** `PlanExecutor` (Core Runtime)
*   **Consumer:** `StepProcessor` (Core Runtime)

**Payload Schema (`StepEvent.v1`):**
```json
{
  "title": "StepEvent.v1",
  "type": "object",
  "required": ["plan_id", "step_id", "step_index", "step_type", "instructions"],
  "properties": {
    "plan_id":     { "type": "string", "description": "ID of the parent plan" },
    "step_id":     { "type": "string", "description": "Unique ID for this step" },
    "step_index":  { "type": "integer", "minimum": 0, "description": "Sequence position within the plan" },
    "step_type":   { "enum": ["LLM_CALL", "TOOL_CALL", "MEMORY_OP", "EXTERNAL_API"], "description": "Type of action to perform" },
    "instructions":{ "type": "string", "description": "Natural language or structured instruction for the step" },
    "parameters":  { "type": "object", "additionalProperties": true, "description": "Step-specific parameters (e.g., prompt, tool name, args)" }
  }
}
```

#### 3.2 `StepResultEvent` Payload (Response)

Represents the outcome of executing a step, published by the `StepProcessor`. Consumed for observability and potentially by `PlanExecutor` for dynamic plan adjustments.

*   **Iggy Topic:** `agent.steps.results`
*   **Producer:** `StepProcessor` (Core Runtime)
*   **Consumers:** `PlanExecutor`, Observability Layer

**Payload Schema (`StepResultEvent.v1`):**
```json
{
  "title": "StepResultEvent.v1",
  "type": "object",
  "required": ["step_id", "status"],
  "properties": {
    "step_id": { "type": "string", "description": "ID matching the originating StepEvent" },
    "status":  { "enum": ["SUCCEEDED", "FAILED", "RETRYING", "CANCELLED"], "description": "Execution outcome" },
    "output":  { "type": ["string", "object", "null"], "description": "Result data from the step execution" },
    "error":   {
      "type": ["object", "null"],
      "properties": {
        "kind":  { "type": "string", "description": "Categorical error type (e.g., 'ProviderError', 'ToolExecutionError')" },
        "detail":{ "type": "string", "description": "Detailed error message or description" }
      }
    },
    "metrics": {
      "type": "object",
      "description": "Performance metrics for the step execution",
      "properties": {
        "latency_ms":      { "type": "number", "description": "Execution time in milliseconds" },
        "prompt_tokens":   { "type": "integer", "description": "Tokens used in prompt (if applicable)" },
        "completion_tokens": { "type": "integer", "description": "Tokens generated in completion (if applicable)" },
        "cost_usd":        { "type": "number", "description": "Estimated cost in USD (if applicable)" }
      }
    }
  }
}
```

### 4. Context / Memory Service Messages

Used for interacting with the `MemoryService`. While primary interaction might be synchronous (e.g., gRPC), these schemas can be used for asynchronous operations (e.g., bulk updates) via Iggy.

*   **Iggy Topic (Optional/Async):** `agent.memory.ops`
*   **Primary Interaction:** `ContextManager` ↔ `MemoryService` (Synchronous, e.g., gRPC)

#### 4.1 `MemoryRequest` Payload

**Payload Schema (`MemoryRequest.v1`):**
```json
{
  "title": "MemoryRequest.v1",
  "type": "object",
  "required": ["op_id", "operation", "namespace"],
  "properties": {
    "op_id":     { "type": "string", "description": "Unique ID for the memory operation" },
    "operation": {
      "enum": ["READ", "WRITE", "UPSERT", "DELETE", "QUERY_EMBEDDINGS"],
      "description": "The type of memory operation requested"
    },
    "namespace": { "type": "string", "description": "Scope for the operation (e.g., tenant/user/personality)" },
    "keys":      { "type": "array", "items": { "type": "string" }, "description": "Keys for READ/DELETE operations" },
    "data":      { "type": ["object","array","null"], "description": "Data payload for WRITE/UPSERT operations" },
    "query":     { "type": ["string","object","null"], "description": "Query details for QUERY_EMBEDDINGS (e.g., query text, top_k)" }
  }
}
```

#### 4.2 `MemoryResponse` Payload

**Payload Schema (`MemoryResponse.v1`):**
```json
{
  "title": "MemoryResponse.v1",
  "type": "object",
  "required": ["op_id", "status"],
  "properties": {
    "op_id":  { "type": "string", "description": "ID matching the originating MemoryRequest" },
    "status": { "enum": ["OK", "ERROR"], "description": "Outcome of the operation" },
    "data":   { "type": ["object","array","null"], "description": "Data returned from READ or QUERY operations" },
    "error":  {
      "type": ["object", "null"],
      "description": "Error details if status is ERROR",
       "properties": {
         "kind": { "type": "string" },
         "detail": { "type": "string" }
        }
     }
  }
}
```

### 5. Provider Adapter Layer Calls

Used for interactions between the Core Runtime and the `ProviderAdapterLayer`. These are typically synchronous (e.g., gRPC) but defined here for completeness and potential audit/replay scenarios.

*   **Primary Interaction:** Core Runtime ↔ `ProviderAdapterLayer` (Synchronous, e.g., gRPC)

#### 5.1 `ProviderRequest` Payload

**Payload Schema (`ProviderRequest.v1`):**
```json
{
  "title": "ProviderRequest.v1",
  "type": "object",
  "required": ["request_id", "provider", "model", "call_type"],
  "properties": {
    "request_id": { "type": "string", "description": "Unique ID for this provider request" },
    "provider":   { "type": "string", "examples": ["openai","anthropic","grok"], "description": "Target provider identifier" },
    "model":      { "type": "string", "description": "Specific model requested" },
    "call_type":  { "enum": ["COMPLETION","EMBEDDING","IMAGE","AUDIO", "MODERATION"], "description": "Type of call to the provider" },
    "parameters": { "type": "object", "additionalProperties": true, "description": "Provider/model-specific parameters (e.g., temperature, max_tokens)" },
    "payload":    { "type": "object", "description": "Main input payload (e.g., prompt object, text chunks for embedding)" }
  }
}
```

#### 5.2 `ProviderResponse` Payload

**Payload Schema (`ProviderResponse.v1`):**
```json
{
  "title": "ProviderResponse.v1",
  "type": "object",
  "required": ["request_id", "status"],
  "properties": {
    "request_id": { "type": "string", "description": "ID matching the originating ProviderRequest" },
    "status":     { "enum": ["OK","ERROR"], "description": "Outcome of the provider call" },
    "output":     { "type": ["string","object","null"], "description": "Result from the provider (e.g., completion text, embedding vectors)" },
    "usage": {
      "type": "object",
      "description": "Token usage and cost metrics",
      "properties": {
        "prompt_tokens":     { "type": "integer" },
        "completion_tokens": { "type": "integer" },
        "cost_usd":          { "type": "number" }
      }
    },
    "error": {
      "type": ["object", "null"],
      "description": "Error details if status is ERROR",
       "properties": {
         "kind": { "type": "string" },
         "detail": { "type": "string" }
       }
    }
  }
}
```

### 6. Summary of Message Flows

| Interaction             | Producer → Consumer(s)                       | Iggy Topic             | Message Type (Payload)      | Primary Comms    |
| :---------------------- | :------------------------------------------- | :--------------------- | :-------------------------- | :--------------- |
| User request arrives    | API Layer → TurnManager                      | `agent.turns.requests` | `TurnEvent.v1`              | Async (Iggy)     |
| Plan step execution req | PlanExecutor → StepProcessor(s)              | `agent.steps.requests` | `StepEvent.v1`              | Async (Iggy)     |
| Step execution result   | StepProcessor → PlanExecutor & Observability | `agent.steps.results`  | `StepResultEvent.v1`        | Async (Iggy)     |
| Memory CRUD             | ContextManager ↔ MemoryService               | `agent.memory.ops`*    | `MemoryRequest`/`Response.v1` | Sync (gRPC)*     |
| Provider call           | Core Runtime ↔ ProviderAdapter               | —                      | `ProviderRequest`/`Response.v1` | Sync (gRPC)      |

*\*Memory operations primarily synchronous (gRPC), but can use Iggy topic for async/bulk operations.*

### 7. Next Steps for Schemas

1.  **Finalization & Versioning:** Formalize these schemas, establish strict semantic versioning rules (using `spec_version`), and **implement the Schema Registry strategy outlined in the Iggy Integration section.**
2.  **Code Generation:** Generate Python dataclasses or Pydantic models from these schemas to ensure type safety in the codebase. Generate Protobuf definitions for gRPC interactions.
3.  **Contract Testing:** Implement integration tests that validate message production and consumption against these schemas, **integrated into the CI/CD pipeline with compatibility checks.**
4.  **Observability Integration:** Ensure trace IDs (`trace_id`) are propagated correctly within the envelope and used consistently across logs and metrics related to these events.

## Error Handling Strategy

A robust error handling strategy is essential for the resilience, stability, and usability of the Agent Shell. This section outlines the principles and approaches for managing errors across different components and scenarios.

### General Principles

1.  **Standardization**: Utilize consistent error structures and codes across components, primarily leveraging the `error` object defined in message schemas (`StepResultEvent`, `MemoryResponse`, `ProviderResponse`) containing `kind` and `detail` fields.
2.  **Comprehensive Logging**: Log all errors with appropriate severity levels (`error`, `critical`) using the standardized `structlog` setup. Ensure logs include component context, relevant IDs (`trace_id`, `turn_id`, `step_id`, `user_id`), and stack traces where applicable. The mandatory `trace_id` enables correlation across distributed services. Use structured JSON logging for easier aggregation and analysis (See Observability Layer).
3.  **Clear User Feedback**: Provide meaningful (but not overly technical) error messages to end-users via the API Layer when a request cannot be fulfilled successfully. Internal system errors should map to user-friendly responses.
4.  **Fail Fast (Where Appropriate)**: Critical configuration errors or unrecoverable internal state issues should lead to component restarts or clear failure signals rather than continuing in an unstable state.
5.  **Idempotency**: Design operations, especially those triggered by Iggy events, to be idempotent where possible to handle message redelivery safely after failures.

### Error Types and Handling Strategies

1.  **Transient Errors**:
    *   **Examples**: Temporary network issues, rate limits (429 errors), short-lived provider unavailability (5xx errors), Iggy connection blips.
    *   **Strategy**: Implement **automatic retries** with **exponential backoff and jitter**. This will be applied by:
        *   `ProviderAdapterLayer`: For calls to external LLM APIs.
        *   `MemoryService` / `ContextManager`: For calls to the underlying database or cache if applicable.
        *   `Iggy Integration Layer`: For connection attempts and publish/subscribe operations.
    *   **Configuration**: Max retries, backoff factor, and jitter will be configurable in `config.toml`.

2.  **Persistent External Failures**:
    *   **Examples**: Invalid API keys (401/403 errors), consistent provider outages, database connection refused, Iggy server permanently unavailable.
    *   **Strategy**: Implement **circuit breakers** (e.g., using libraries like `pybreaker`) within the client components (`ProviderAdapterLayer`, `MemoryService` client interface, `Iggy Integration Layer`).
        *   After a configured number of consecutive failures, the circuit opens, failing subsequent requests immediately without attempting the call.
        *   The circuit attempts to close after a timeout, allowing a single request through to test recovery.
    *   **Action**: Open circuits should trigger alerts via the Observability Layer.

3.  **Configuration Errors**:
    *   **Examples**: Malformed `config.toml`, missing required configuration values, invalid environment variables for secrets.
    *   **Strategy**: Validate configuration thoroughly on service startup (`ConfigLoader`).
        *   Fatal configuration errors (e.g., missing essential keys, parsing failures) MUST prevent the service/component from starting successfully (fail fast).
        *   Log detailed error messages indicating the configuration issue.

4.  **Planning and Step Execution Errors**:
    *   **Examples**: LLM fails to generate a valid plan, tool specified in a step doesn't exist or fails during execution, memory operation within a step fails, step dependencies not met, step timeout.
    *   **Strategy**: Handled primarily by the `PlanExecutor` and `StepProcessor`:
        *   Failures are reported via the `StepResultEvent` with `status: FAILED` and a detailed `error` object (`kind`, `detail`).
        *   `PlanExecutor` may attempt plan repair or generation retries based on failure type (configurable).
        *   `StepProcessor` may have step-level retry logic (for transient errors during execution, distinct from provider retries).
        *   Unhandled step failures within a plan typically result in the turn failing gracefully, with an appropriate error reported back to the user via the API Layer.
        *   Step timeouts (configurable) lead to a FAILED status.
        *   **Compensation**: For failures occurring after previous steps have made irreversible side effects (e.g., external API calls, database writes), a compensation strategy (e.g., Saga pattern) needs to be invoked if defined for the failed step sequence. This is currently marked as a future enhancement requiring detailed design (see Core Runtime -> StepProcessor).

5.  **Memory Service Errors**:
    *   **Examples**: Database query errors, vector search failures, cache connection errors, data serialization issues.
    *   **Strategy**: Handled within the `MemoryService` itself and its client interface (`ContextManager`):
        *   Internal retries/circuit breakers for backend connections (DB, Cache).
        *   Return standardized `MemoryResponse` with `status: ERROR` and error details.
        *   `ContextManager` might attempt to use cached data (if available and appropriate) when reads fail, logging a warning.
        *   Critical failures preventing context load/save will propagate up and likely cause the turn to fail.

6.  **Iggy Communication / Messaging Errors**:
    *   **Examples**: Failure to publish messages, failure to deserialize incoming messages, persistent connection loss.
    *   **Strategy**: Handled by the `Iggy Integration Layer` / `EventPublisherSubscriber`:
        *   Retries for transient publish/connection issues.
        *   Circuit breaker for persistent connection failures.
        *   Deserialization errors indicate schema mismatch or data corruption – log detailed error, **publish message to the appropriate Dead Letter Queue (DLQ) as defined in the Iggy Integration section**, and trigger alerts.
        *   Failure to acknowledge messages after processing (if using manual commits) requires careful handling to avoid duplicate processing (rely on idempotency). **Messages that repeatedly fail processing after retries due to non-transient issues should also be routed to the DLQ.**

7.  **Validation Errors**:
    *   **Examples**: Malformed API requests, invalid personality manifest (`manifest.yaml`), invalid parameters in events.
    *   **Strategy**: Reject the request/event early with a clear error message.
        *   API Layer: Return appropriate HTTP status codes (e.g., 400 Bad Request, 422 Unprocessable Entity) with descriptive error payloads.
        *   Personality Pack Manager: Reject invalid packs during loading, log detailed validation errors.
        *   Event Consumers: Validate incoming event payloads against schemas; invalid messages should be logged and **potentially routed to a DLQ if persistent validation failures occur after source correction attempts.**

### Observability and Alerting

*   **Logging**: All error handling logic (retries, circuit breaker state changes, fallback execution, final failures) MUST be logged using `structlog` with appropriate context and correlation IDs (`trace_id`).
*   **Logging**: All error handling logic (retries, circuit breaker state changes, fallback execution, final failures) MUST be logged with correlation IDs.
*   **Metrics**: Key error metrics (e.g., retry counts, circuit breaker states, rate of failed requests/steps/turns per type) MUST be exposed via the `Metrics Collector`. **Metrics for DLQ size per topic MUST also be exposed.**
*   **Alerting**: Configure alerts in Prometheus/Grafana based on critical error metrics (e.g., high rate of 5xx errors from providers, circuit breakers opening, persistent Iggy connection failures, high rate of failed turns, **DLQ depth exceeding thresholds**). **Service Level Objectives (SLOs) for key operations (e.g., p95 turn latency, step execution success rate) should be defined and alerts configured for SLO violations.**

This multi-faceted approach ensures that errors are handled gracefully, system stability is maintained, and sufficient information is available for debugging and monitoring.

## Security Considerations

Security is paramount for the Agent Shell. This section outlines key security considerations and mitigation strategies across the architecture.

### 1. Authentication and Authorization

*   **API Layer Access**: All external API endpoints (REST, WebSocket, gRPC) MUST be protected by robust authentication mechanisms. **The primary standard will be OAuth 2.1 using JWT Bearer tokens, obtained via a dedicated authentication service (details TBD).** API Key authentication MAY be used for trusted backend service-to-service communication.
*   **Authorization**: While detailed role-based access control (RBAC) might be a future enhancement, initial authorization will focus on ensuring authenticated principals (users, services) can only access resources associated with their identity or tenancy (e.g., their own memory, sessions). Further policy enforcement (e.g., using Open Policy Agent - OPA) could be integrated later if needed.

### 2. Data Security

*   **Data in Transit**: All external communication (API Layer) and internal service-to-service communication (including connections to Iggy, databases, caches) MUST use TLS (ideally TLS 1.3) for encryption. Configuration should enforce strong cipher suites.
*   **Data at Rest**:
    *   Sensitive configuration values (API keys, passwords) MUST NOT be stored in code or `config.toml` directly. They should be loaded from environment variables or a secure secrets management system (e.g., HashiCorp Vault, AWS Secrets Manager). See "Secret Management" below.
    *   Persistent data stored by the `MemoryService` (user context, conversation history, knowledge documents) should be encrypted at rest, leveraging database-level encryption features (e.g., PostgreSQL TDE, filesystem encryption).
    *   **Iggy At-Rest Encryption**: Configure Iggy server-side data encryption (e.g., using AES-256-GCM) for message logs stored on disk.
*   **PII Handling**: Sensitive Personally Identifiable Information (PII) within conversation history or user context requires careful handling. Implement PII detection and redaction/masking mechanisms where appropriate (e.g., before logging or storing in less secure environments), based on defined data privacy policies.

### 3. Infrastructure Security

*   **Network Segmentation**: Deploy components in isolated network segments (e.g., VPC subnets) with strict firewall rules, allowing only necessary communication between services on specific ports.
*   **Least Privilege**: Service accounts and infrastructure roles MUST be configured with the minimum permissions required for their function.
*   **Regular Patching**: Establish a process for regularly updating OS, dependencies, and base container images to mitigate known vulnerabilities.

### 4. Personality Pack Security

*   **Tool Sandboxing (CRITICAL)**: As detailed in the Personality Pack Manager section, arbitrary code execution by tools is a major risk. **Implementing a robust sandbox (e.g., Wasm, Firecracker MicroVMs) is essential.** The sandbox MUST restrict filesystem access, network calls (allowlisting specific domains/IPs if necessary), and resource consumption (CPU, memory).
*   **Input Validation**: Inputs passed from LLM-generated plans to tools MUST be validated to prevent injection attacks or unexpected behavior.
*   **Output Sanitization**: Outputs from tools, especially those interacting with external systems, may need sanitization before being included in prompts or responses.
*   **Pack Vetting**: Implement processes (potentially automated checks in CI/CD) to scan personality packs for malicious code or vulnerable dependencies before loading.

### 5. Provider Security

*   **API Key Management**: Securely store and manage API keys for LLM providers (see Secret Management).
*   **Data Privacy**: Be mindful of data sent to external LLM providers. Avoid sending unnecessary PII. Review provider data usage policies.

### 6. Iggy Security Specifics

*   **Authentication**: Use strong credentials (username/password or Personal Access Tokens) for client connections, loaded securely.
*   **Authorization**: Leverage Iggy\'s stream/topic level permissions if available and mature, ensuring clients can only publish/subscribe to authorized topics.
*   **Encryption**: Mandate TLS 1.3 for transport encryption (QUIC or TCP). Configure server-side at-rest encryption (AES-256-GCM).
*   **Network Exposure**: Expose Iggy ports only to trusted internal networks.
*   **Client Authentication**: Consider mandatory client certificate authentication (mTLS) for enhanced security, especially for sensitive producers/consumers.

### 7. Secret Management

*   **Mechanism**: Avoid storing secrets directly in configuration files or environment variables in plain text in production. Use environment variables loaded from a `.env` file for local development, and secure environment variable injection (e.g., Kubernetes Secrets, Vault) in production.
*   **Recommended Approach**: Integrate with a dedicated secrets management system (e.g., HashiCorp Vault, cloud provider equivalents like AWS Secrets Manager, GCP Secret Manager) for production environments. For local development, use a `.env` file (which MUST be added to `.gitignore`) and reference environment variables within `config.toml` using placeholder syntax (e.g., `api_key = "${PROVIDER_API_KEY}"`). The `ConfigLoader` resolves these placeholders against environment variables.
*   **Implementation**: Components requiring secrets (e.g., `ConfigLoader`, `ProviderAdapterLayer` for API keys, `MemoryService` for DB passwords) retrieve them via the `ConfigLoader` which reads from environment variables (sourced from `.env` locally or injected in production).
*   **Rotation**: Implement automated secret rotation policies within the secrets management system (production) or manually update `.env` files and environment variables as needed.

### 8. Threat Modeling & Auditing

*   **Threat Modeling**: Conduct regular threat modeling exercises to identify potential vulnerabilities across different components and trust boundaries (e.g., API layer, personality tools, data storage, provider interactions).
*   **Audit Logging**: Ensure critical actions (e.g., authentication attempts, configuration changes, personality loading, sensitive data access) are logged securely and immutably (if required by compliance) for auditing purposes. Integrate with the Observability Layer.
*   **Penetration Testing**: Schedule regular penetration tests by independent security experts to proactively identify weaknesses.

By addressing these considerations throughout the design and implementation lifecycle, the Agent Shell can maintain a strong security posture.

## Development Lifecycle and CI/CD

A robust CI/CD pipeline is essential for ensuring code quality, security, and reliable deployments. Development utilizes Poetry for dependency management and the Aegis framework for task tracking.

### Pipeline Stages

1.  **Linting & Static Analysis**: Run code formatters (e.g., `black`), linters (e.g., `ruff`, `flake8`), and static type checkers (e.g., `mypy`) on every commit/PR.
2.  **Unit Testing**: Execute component-level unit tests with high code coverage targets using `pytest`. Mock external dependencies (LLM providers, databases, Iggy).
3.  **Dependency & Security Scanning**:
    *   Scan Python dependencies defined in `poetry.lock` for known vulnerabilities (e.g., `pip-audit --requirement poetry.lock`, `safety check --file poetry.lock`).
    *   Perform static application security testing (SAST) scans on the codebase.
    *   Scan container images for OS-level vulnerabilities (e.g., `trivy`).
    *   Scan Personality Packs (especially tool code) for vulnerabilities or malicious patterns.
4.  **Integration Testing**:
    *   Run tests involving interactions between multiple components.
    *   Requires ephemeral instances of dependencies (e.g., Iggy, Postgres/pgvector, Redis) spun up using Docker Compose or testcontainers.
    *   **Contract Testing**: Validate interactions against defined schemas (OpenAPI, Protobuf, Iggy event schemas). Ensure producers and consumers adhere to the agreed contracts, including **schema compatibility checks** (backward, forward) using the Schema Registry.
5.  **Build & Packaging**: Build container images for deployment. Package Personality Packs if using an advanced format (e.g., OCI).
6.  **Deployment Strategy**: Deploy to staging/production environments using defined strategies:
    *   **Canary Deployments**: Gradually roll out changes to a small subset of users/traffic for components like the Core Runtime.
    *   **Blue/Green Deployments**: Deploy new versions alongside old ones, switching traffic once the new version is validated (suitable for stateless components like Provider Adapters).
    *   Monitor deployment health closely using Observability Layer data.
7.  **Post-Deployment Validation**: Run smoke tests against the newly deployed version.

### Key Requirements

*   **Infrastructure as Code (IaC)**: Manage infrastructure provisioning (Kubernetes manifests, Terraform) through code.
*   **Automated Testing**: All test suites (unit, integration, contract) MUST be automated and run within the pipeline.
*   **Environment Parity**: Strive for similarity between development, staging, and production environments. Use `poetry install` to ensure consistent dependencies.
*   **Pipeline Security**: Secure the CI/CD pipeline itself (access controls, secret management for deployment credentials).

### Local Development Setup
1. Clone the repository.
2. Ensure Poetry is installed.
3. Run `poetry install` to install dependencies based on `poetry.lock`.
4. Copy `.env.example` to `.env` and populate secrets.
5. Use `poetry run <command>` (e.g., `poetry run python server.py`) or `poetry shell` to run commands within the virtual environment.
6. Use Aegis commands (e.g., `poetry run aegis task list`, `poetry run aegis start TASK-XXX`) for task management.

## Disaster Recovery and Compliance

Planning for failures and adhering to compliance standards is crucial for production readiness.

### Disaster Recovery (DR)

*   **Recovery Point Objective (RPO)**: Maximum acceptable data loss (e.g., 1 hour, 15 minutes). **[Target TBD]**
*   **Recovery Time Objective (RTO)**: Maximum acceptable downtime to restore service after a disaster (e.g., 4 hours, 1 hour). **[Target TBD]**
*   **Backup Strategy**:
    *   **Memory Service (Vector DB)**: Implement regular automated backups (e.g., using `pg_dump` for Postgres/pgvector, provider-specific snapshot tools). Store backups securely off-site (e.g., cloud storage). Define backup frequency based on RPO.
    *   **Memory Service (Cache - Redis)**: If Redis is used for more than just volatile caching (e.g., storing state that isn't immediately reconstructed from DB), configure Redis persistence (RDB snapshots, AOF) and backups.
    *   **Apache Iggy**: Iggy persists message logs to disk. Backup these log segment files regularly according to the RPO. Consider Iggy\'s built-in replication for HA, which also contributes to DR.
    *   **Configuration**: Backup `config.toml` and related environment configurations.
*   **Restore Procedures**: Document and regularly test procedures for restoring the system from backups in a separate DR environment.
*   **High Availability (HA)**: Implement HA measures outlined in other sections (Iggy clustering, redundant component instances, database replication) to minimize the need for full DR invocation.

### Compliance

*   **Requirements Identification**: Determine applicable compliance standards based on the intended use case and data handled (e.g., GDPR, HIPAA, SOC 2).
*   **Audit Logging**: Implement secure, potentially immutable audit logging for significant events (logins, data access, configuration changes, administrative actions). Retain logs according to compliance requirements.
*   **Data Governance**: Establish clear policies for data classification, retention, access control, and deletion (including user-requested GDPR deletion) and ensure the Memory Service and other components adhere to them.
*   **Security Controls**: Ensure security measures outlined in the "Security Considerations" section align with chosen compliance framework controls.
*   **Regular Audits**: Plan for internal or external audits to verify compliance.

**Note**: Specific RPO/RTO targets and detailed compliance requirements need to be defined based on business needs and risk assessment.

## Scalability Strategy

The Agent Shell architecture is designed for horizontal scalability, enabling it to handle increasing load by adding more resources rather than requiring larger individual components. The core strategy relies on stateless or state-minimized services communicating via the high-performance Apache Iggy message bus.

### Core Principle: Horizontal Scaling via Statelessness and Messaging

*   **Stateless Services**: Components like the API Layer handlers, `TurnManager`, `PlanExecutor`, `StepProcessor`, and `ProviderAdapterLayer` are designed to be primarily stateless. They process requests or events based on the input data and context retrieved from the `MemoryService` or passed via messages.
*   **Horizontal Scaling**: Load is distributed across multiple instances (replicas/pods) of these stateless services.
*   **Message Bus**: Apache Iggy decouples components, allowing producers and consumers to scale independently. Consumer groups enable parallel processing of messages from Iggy topics.
*   **State Management**: Persistent state (conversation history, user context, knowledge) is managed externally by the `MemoryService`. Short-term operational state or caches (like in `ContextManager`) are either per-instance (requiring careful state loading) or ideally backed by a distributed cache (like Redis within the Memory Service) to support scaling.

### Component-Specific Scaling Strategies

1.  **API Layer (FastAPI/gRPC/WebSocket)**:
    *   **Scaling**: Run multiple replicas behind a standard load balancer (e.g., Kubernetes Service/Ingress).
    *   **WebSocket Considerations**: Scaling WebSocket handlers requires careful state management if connections need data associated with them across multiple replicas. Options include:
        *   **Sticky Sessions**: Load balancer routes a specific client to the same replica (can lead to uneven load).
        *   **Shared State Backend**: Using a distributed cache (e.g., Redis pub/sub via `MemoryService`) to broadcast messages to the correct client connection, regardless of which API replica it's connected to.

2.  **Core Runtime (`TurnManager`, `PlanExecutor`, `StepProcessor`)**:
    *   **Scaling**: Run multiple replicas for each component type.
    *   **Load Balancing**: Apache Iggy **Consumer Groups** naturally distribute the message load (e.g., `TurnEvent`, `StepEvent`) across available consumer instances (replicas).
    *   **Idempotency**: Event handling logic must be idempotent to handle potential message redelivery during scaling events or failures safely.

3.  **Provider Adapter Layer**:
    *   **Scaling**: Scales implicitly with the Core Runtime components that call it. It's largely stateless.
    *   **Limitations**: Throughput can be limited by external LLM provider API rate limits, quotas, and latencies. The circuit breaker pattern helps manage persistent provider issues.

4.  **Memory Service**:
    *   **Scaling**: Highly dependent on the chosen backend technologies (Vector DB, Cache).
    *   **Vector Database**:
        *   *pgvector (Postgres):* Scale reads via read replicas. Write scaling may require partitioning or upgrading the primary instance. Consider connection pooling.
        *   *Dedicated Vector DBs (e.g., Weaviate, Pinecone):* Often offer built-in clustering, sharding, and replication mechanisms. Consult specific provider documentation.
    *   **Cache (Redis)**: Scale using Redis Cluster for sharding and high availability, or Redis Sentinel for failover with read replicas.

5.  **Personality Pack Manager**:
    *   **Current Model**: Each Core Runtime instance loads needed personality packs via the Manager.
    *   **Scaling Consideration**: If the number or size of packs becomes very large, loading them into every Core Runtime replica might become inefficient (memory usage, startup time).
    *   **Potential Alternative (Future)**: Could be refactored into a separate shared service providing `PersonalityInstance` details or proxying tool calls, reducing per-replica load. Requires further research if needed.

6.  **Apache Iggy Server**:
    *   **Scaling Message Processing**: Achieved via partitioning streams/topics and scaling consumer components (see below).
    *   **Scaling the Bus Itself**: For very high throughput or high availability requirements, Iggy's developing clustering and replication features will be necessary. Monitor the maturity and operational characteristics of Iggy clustering for production use.

### Key Scaling Mechanisms

*   **Iggy Partitioning**:
    *   **Strategy**: Streams (e.g., `turns`, `steps`) should be partitioned, typically using keys like `session_id` or `user_id`.
    *   **Benefits**: Allows parallel processing by multiple consumers in a group (each consumer handles a subset of partitions). Ensures messages related to the same session/user are processed in order by a single consumer instance at a time (within that consumer group).
    *   **Configuration**: Number of partitions per stream/topic is configurable.
*   **Iggy Consumer Groups**:
    *   **Mechanism**: Multiple instances of a service (e.g., `StepProcessor`) subscribe using the same consumer group ID. Iggy distributes partitions among them.
    *   **Benefit**: Enables straightforward horizontal scaling of message consumers.
*   **Autoscaling (Kubernetes HPA)**:
    *   **Mechanism**: Configure Horizontal Pod Autoscalers for API, Core Runtime, and potentially Memory Service components.
    *   **Metrics**: Scale based on standard metrics (CPU, Memory usage) and potentially custom metrics (e.g., Iggy consumer group lag - the number of unprocessed messages, available via Iggy metrics).

### Potential Bottlenecks and Considerations

*   **Slow Tools/Steps**: Long-running tool calls or complex LLM steps within the `StepProcessor` can become bottlenecks, limiting overall turn throughput. Optimize tools and consider asynchronous tool execution patterns.
*   **Complex Plan Generation**: If `PlanExecutor` involves very slow LLM calls or complex logic, it could limit the rate of new plan initiations.
*   **Database Contention**: High load on the `MemoryService` backend (vector DB writes/reads, context storage) can cause bottlenecks. Requires appropriate database sizing, indexing, and potential scaling (read replicas, sharding).
*   **Iggy Partition Hotspots**: If partitioning keys are not well-distributed (e.g., one user generates vastly more traffic), specific partitions and the consumers handling them can become overloaded. Monitor partition load.
*   **Load Testing**: Crucial for identifying actual bottlenecks, validating scaling assumptions, and determining appropriate resource allocation (CPU, memory, replica counts) under realistic load profiles.

This strategy provides a solid foundation for scaling the Agent Shell. Specific configurations and tuning will depend on observed performance under load.

## Apache Iggy vs. Kafka

The architecture leverages Apache Iggy as a direct replacement for Kafka with several advantages:

### Performance Benefits

- **Rust-based Efficiency**: Built with Rust for predictable resource usage without GC spikes[3][5][17]
- **High Throughput**: Capable of processing millions of messages per second[5][22]
- **Low Resource Footprint**: More efficient resource utilization compared to Kafka[3][6]

### Simplicity Advantages

- **Single Binary**: Simpler deployment with no external dependencies[20]
- **Built-in Management**: Includes CLI and Web UI for administration[3][5][17]
- **Multiple Transport Protocols**: Supports TCP, QUIC, and HTTP transport[3][5][17]

### Feature Parity with Kafka

- **Persistent Append-only Log**: Messages stored persistently with similar semantics to Kafka[7][8]
- **Streams, Topics, Partitions**: Similar structural concepts to Kafka[7][8]
- **Consumer Groups**: Support for parallel processing with consumer groups[7][22]

### Advanced Capabilities

- **Message Deduplication**: Built-in support for eliminating duplicate messages[3][5]
- **Data Encryption**: Native support for securing sensitive data[3][5]
- **Multiple SDKs**: Support for Python, Rust, and other languages[3][5][10]

## Iggy Configuration for Agent Shell

### Stream and Topic Structure

```
agent-streams/
├── turns/
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

Each stream will be configured with appropriate partitioning, retention policies, and consumer groups:

- **Partitioning Strategy**: Partition by tenant_id or session_id for scalability[7]
- **Retention Policies**: Configure different retention periods based on data importance[7][19]
- **Consumer Groups**: Define consumer groups for different components for parallel processing[7][22]

## Implementation Considerations

### Python SDK Integration

The Agent Shell will leverage Iggy's Python SDK for integration:

```python
from iggy.client import IggyClient

# Create client with connection string
client = IggyClient.from_connection_string("iggy://user:password@localhost:8090")

# Create producer for sending messages
producer = client.producer("agent-streams", "turns").build()
producer.init()

# Send messages to Iggy
messages = [Message.from_str("Agent response data")]
producer.send(messages)

# Create consumer for reading messages
consumer = client.consumer_group("agent-shell", "agent-streams", "events").build()
consumer.init()

# Process incoming messages
async for message in consumer:
    # Handle event
    process_event(message)
```

This integration enables seamless communication between components via Iggy streams[10][13].

### Deployment Architecture

The Agent Shell deployment will consist of containerized components with Iggy as the central message bus:

```mermaid
graph TD
    subgraph Kubernetes Cluster
        direction LR
        APIService[API Service]
        CoreRuntime[Core Runtime]
        ProviderAdapters[Provider Adapters]
        MemoryService[Memory Service]
        ApacheIggy[Apache Iggy]
        Observability[Observability Stack]

        APIService --> ApacheIggy
        CoreRuntime --> ApacheIggy
        ProviderAdapters --> CoreRuntime
        MemoryService --> CoreRuntime
        CoreRuntime --> Observability
        ApacheIggy --> Observability

        style APIService fill:#lightgrey
        style CoreRuntime fill:#lightgrey
        style ProviderAdapters fill:#lightgrey
        style MemoryService fill:#lightgrey
        style ApacheIggy fill:#lightblue
        style Observability fill:#lightgreen
    end
```

### Replication and Clustering

For production environments, Iggy's developing replication capabilities will be leveraged:

- **Viewstamped Replication**: Utilizing Iggy's evolving replication capabilities[12][21][23]
- **Cluster Configuration**: Configuring Iggy for high availability and fault tolerance[20][23]
- **Data Redundancy**: Ensuring critical data is replicated across nodes[12][21]

## Conclusion

This architecture design provides a comprehensive framework for implementing the Agent Shell project with Apache Iggy as the central message streaming platform. The design adheres to the PRD requirements while leveraging Iggy's advantages over traditional Kafka deployments.

### Next Steps

1. **Component Specification**: Detail the interfaces and classes for each component
2. **Iggy Integration Proof-of-Concept**: Develop a small POC to validate Iggy integration
3. **Development Roadmap**: Create detailed development tasks aligned with PRD milestones
4. **Stakeholder Review**: Present architecture for final approval from Engineering Lead and Product Owner

This architecture positions the Agent Shell project for success by providing a modern, efficient, and scalable foundation that meets all the requirements outlined in the PRD.

Sources
[1] TASK-001.md https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/64137834/5515ecf5-6951-4546-a3a7-22078f56c7bb/TASK-001.md
[2] prd.md https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/64137834/3aefb70d-4489-46ba-8494-980ad03e379c/prd.md
[3] iggy.apache.org https://iggy.apache.org
[4] Hello from Hyper-Efficient Message Streaming at Laser Speed. | Hyper-Efficient Message Streaming at Laser Speed. https://iggy.apache.org/
[5] Apache Iggy (Incubating) - Message streaming platform https://iggy.rs
[6] Top 6 Kafka Alternatives for Data Streaming in 2025 - Estuary https://estuary.dev/blog/kafka-alternatives/
[7] Architecture | Iggy.rs https://docs.iggy.rs/introduction/architecture
[8] Iggy joins the Apache Incubator https://blog.iggy.rs/posts/apache-incubator/
[9] Iggy.rs — one year of building the message streaming https://blog.iggy.rs/posts/one-year-of-building-the-message-streaming/
[10] Intro | Iggy.rs https://docs.iggy.rs/sdk/python/intro
[11] Using prometheus - Inspektor Gadget https://inspektor-gadget.io/docs/v0.38.1/legacy/prometheus/
[12] Technology Radar & current goals - Iggy.rs https://blog.iggy.rs/posts/technology-radar-and-currrent-goals/
[13] iggy::http::client - Rust - Docs.rs https://docs.rs/iggy/latest/iggy/http/client/index.html
[14] Apache Iggy (Incubating) - iggyrs #otel #opentelemetry - LinkedIn https://www.linkedin.com/posts/apache-iggy_iggyrs-otel-opentelemetry-activity-7252560060071956481-xhwN
[15] Apache Iggy: Hyper-Efficient Message Streaming at Laser Speed https://github.com/apache/iggy
[16] Introduction | Iggy.rs https://docs.iggy.rs/server/introduction
[17] Apache Iggy - The Apache Software Foundation https://iggy.apache.org
[18] Iggy.rs - Technology Radar & current goals https://iggy.apache.org/blogs/2024/10/28/technology-radar-and-currrent-goals
[19] Getting started - Iggy.rs https://docs.iggy.rs/introduction/getting-started
[20] Iggy Proposal - The Apache Software Foundation https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal
[21] Apache Iggy (Incubating) on X: "Replication is an indispensable ... https://x.com/ApacheIggy/status/1843160083284533645
[22] iggy/README.md at master · apache/iggy - GitHub https://github.com/apache/iggy/blob/master/README.md
[23] Sandbox for the future implementation of Iggy.rs clustering feature. https://github.com/iggy-rs/iggy-cluster-sandbox
[24] Apache Iggy (Incubating) (@iggy.rs) — Bluesky https://bsky.app/profile/iggy.rs
[25] Iggy.rs - Technology Radar & current goals : r/rust - Reddit https://www.reddit.com/r/rust/comments/1gdw742/iggyrs_technology_radar_current_goals/
[26] Iggy.rs — one year of building the message streaming : r/rust - Reddit https://www.reddit.com/r/rust/comments/1d35fsb/iggyrs_one_year_of_building_the_message_streaming/
[27] iggy-py · PyPI https://pypi.org/project/iggy-py/
[28] Transparent Benchmarking with Apache Iggy : r/rust - Reddit https://www.reddit.com/r/rust/comments/1irouxk/transparent_benchmarking_with_apache_iggy/
[29] The Guide to Apache Kafka Alternatives - Macrometa https://www.macrometa.com/event-stream-processing/kafka-alternatives
[30] IggyEx - official Elixir client SDK for Iggy.rs message streaming https://elixirforum.com/t/iggyex-official-elixir-client-sdk-for-iggy-rs-message-streaming/61212
[31] iggy 0.6.210 - Docs.rs https://docs.rs/crate/iggy/latest/source/Cargo.toml.orig
[32] Iggy.rs — one year of building the message streaming https://blog.iggy.rs/posts/one-year-of-building-the-message-streaming/
[33] Comparing Apache Kafka alternatives - Redpanda https://www.redpanda.com/guides/kafka-alternatives
[34] Stream Builder | Hyper-Efficient Message Streaming ... - Apache Iggy https://iggy.apache.org/docs/introduction/stream-builder
[35] Welcome | Hyper-Efficient Message Streaming at Laser Speed. https://iggy.apache.org/docs/
[36] About | Hyper-Efficient Message Streaming at Laser Speed. https://iggy.apache.org/docs/introduction/about/
[37] Metrics - Debugging - Lib.rs https://lib.rs/crates/metrics
[38] Compare BlueCats vs. Iggy in 2025 https://slashdot.org/software/comparison/BlueCats-vs-Iggy/
[39] Iggy.rs - message streaming platform : r/rust - Reddit https://www.reddit.com/r/rust/comments/151tjsr/iggyrs_message_streaming_platform/
[40] Official Python client SDK for Iggy.rs message streaming. - GitHub https://github.com/iggy-rs/iggy-python-client
[41] iggy - Tools for consistency based analysis of influence graphs and ... https://bioasp.github.io/iggy/
[42] PostgreSQL Cluster/Replication Aware backup Configuration https://community.commvault.com/self-hosted-q-a-2/postgresql-cluster-replication-aware-backup-configuration-4527
[43] iggy-py - PyPI https://pypi.org/project/iggy-py/0.2.0/
[44] About - Iggy.rs https://docs.iggy.rs/introduction/about
[45] iggy - crates.io: Rust Package Registry https://crates.io/crates/iggy/0.0.4
[46] Args in iggy::args - Rust - Docs.rs https://docs.rs/iggy/latest/iggy/args/struct.Args.html
[47] List of Prometheus Metrics - JupyterHub documentation https://jupyterhub.readthedocs.io/en/stable/reference/metrics.html
[48] High-level SDK | Iggy.rs https://docs.iggy.rs/introduction/high-level-sdk
[49] IGDB API docs: Getting Started https://api-docs.igdb.com
[50] How to Retrieve All Prometheus Metrics - A Step-by-Step Guide https://signoz.io/guides/how-to-get-all-the-metrics-of-an-instance-with-prometheus-api/
[51] Integrations | OpenTelemetry https://opentelemetry.io/ecosystem/integrations/
[52] iggy - crates.io: Rust Package Registry https://crates.io/crates/iggy/0.0.16
[53] Iggy | Public APIs | Postman API Network https://www.postman.com/iggyf
[54] Metric types - Prometheus https://prometheus.io/docs/concepts/metric_types/
[55] OpenTelemetry https://opentelemetry.io
[56] iggy-rs/iggy-node-http-client - GitHub https://github.com/iggy-rs/iggy-node-http-client
[57] Prometheus Metrics: A Practical Guide | Tigera - Creator of Calico https://www.tigera.io/learn/guides/prometheus-monitoring/prometheus-metrics/
[58] Iggy.rs - Technology Radar & current goals https://iggy.apache.org/blogs/2024/10/28/technology-radar-and-currrent-goals

> Written with [StackEdit](https://stackedit.io/). 