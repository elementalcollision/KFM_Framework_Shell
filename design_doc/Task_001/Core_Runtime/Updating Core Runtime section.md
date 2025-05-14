**Updating Core Runtime section**

The user wants me to review the Core Runtime section of an architecture document. This section is the first one mentioned but lacks detail compared to others. I’m thinking of suggesting a dedicated subsection to elaborate on its sub-modules, such as TurnManager, PlanExecutor, and others, explaining their roles and how they interact. A diagram showing the internal components could help clarify this. I'll recommend these improvements to give more structure and detail to the Core Runtime section.

**Providing Core Runtime suggestions**

The user wants me to suggest updates to the architecture document, specifically adding a dedicated subsection for the Core Runtime Layer. This would detail its submodules, their responsibilities, and possibly a diagram. The file the user uploaded isn’t in Canvas, but it’s a regular document, so no changes are needed in Canmore. My plan is to respond with a proposed subsection, including descriptions of the modules and maybe a simple diagram (like ASCII or Mermaid) for clarity.

Thought for 34 seconds

Below is a drop‑in **“Core Runtime Layer”** subsection you can paste right after the heading that currently introduces the runtime (lines 18‑24 of the architecture doc). It describes every internal module, their hand‑off sequence, and how they publish/consume Iggy events. The mermaid diagram matches the style used for the other layers.

---

### **Core Runtime Layer — *detailed design***

#### **1\. Responsibility recap**

* Act as **dispatcher & conductor** of the Turn → Plan → Step workflow.

* Keep **state‑machine logic** encapsulated while delegating heavy work (LLM calls, memory ops, tool invocations) to dedicated micro‑services.

* Emit a **complete event trail** (`turns`, `steps`, `step_results`, `audit`) over Apache Iggy so that horizontal workers, observability, and replay tools remain loosely coupled.

#### **2\. Sub‑modules**

| Sub‑module | Key duties | Consumes | Produces | Failure behaviour |
| ----- | ----- | ----- | ----- | ----- |
| **ConfigLoader** | Load & hot‑reload `config.toml`, env‑vars, personality defaults; expose typed settings to the rest of runtime | — | config change events | atomic swap; last‑good fallback |
| **TurnManager** | Accept `TurnEvent` from API layer, attach `trace_id`, pick personality, load session context | `agent.turns` topic | `PlanRequest` internal msg | 422 on malformed turn |
| **PlanExecutor** | Generate a **Plan DAG** (few‑shot planner or rules engine) and linearise it; create Step descriptors | in‑mem from TurnManager | `StepEvent` messages to `agent.steps` | skips step on planner error, logs |
| **StepProcessor** | Drive each Step (LLM/tool/memory) by invoking the appropriate adapter or service; handle streaming back‑pressure | `agent.step_results` stream | response chunks to WebSocket & `audit` topic | circuit‑break on repeated provider errors |
| **ContextManager** | Read/write conversation history and user prefs through Memory‑Service adapters; provide short‑term cache | sync call to Memory layer | — | retries with stale‑read fallback |
| **EventPublisherSubscriber** | Thin wrapper around Iggy‑Py client; publishes all internal events and subscribes to results with at‑least‑once semantics | Iggy streams | Iggy streams | idempotent writes via `step_id` keys |

#### **3\. Lifecycle flow**

```
sequenceDiagram
    autonumber
    participant API as API Gateway
    participant TM as TurnManager
    participant PE as PlanExecutor
    participant SP as StepProcessor
    participant IG as Apache Iggy
    participant WK as Provider Worker

    API->>IG: TurnEvent
    Note right of IG: stream: agent.turns
    IG-->>TM: TurnEvent
    TM->>PE: PlanRequest (in‑proc)
    PE->>IG: StepEvent(s)
    Note right of IG: stream: agent.steps
    IG-->>WK: StepEvent
    WK-->>IG: StepResultChunk
    Note right of IG: stream: agent.step_results
    IG-->>SP: StepResultChunk
    SP-->>API: WebSocket delta
    SP->>IG: AuditEvent
```

#### **4\. Interaction with other layers**

* **Provider Adapter Layer** – invoked exclusively by `StepProcessor`; adapter selection comes from `ConfigLoader` defaults or personality overrides.

* **Personality Pack Manager** – `TurnManager` fetches the desired `PersonalityInstance` and passes its system‑prompt & tools to `PlanExecutor`.

* **Memory Service** – `ContextManager` handles reads/writes; `StepProcessor` may trigger `memory_*` steps.

* **Observability Layer** – every sub‑module emits structured logs with `trace_id`, while `EventPublisherSubscriber` surfaces per‑topic latency and error metrics.

#### **5\. Concurrency & scaling notes**

* **Stateless** – all per‑turn state lives in Iggy or Memory‑Service, enabling the core runtime pod to scale via K8s HPA on `iggy_consumer_lag`.

* **Idempotency** – `step_id` (ULID) is the primary key in every event payload, allowing re‑processing without duplication.

* **Back‑pressure** – StepProcessor caps concurrent in‑flight steps (configurable, default = 16) and pauses consumption if the output WebSocket buffer exceeds 128 KB.

---

