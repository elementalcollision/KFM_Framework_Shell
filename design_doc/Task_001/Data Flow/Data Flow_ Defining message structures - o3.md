**Defining message structures

Below is a **working first‑cut “wire contract”** for the Agent Shell.  
 Every message that moves across Apache Iggy (or a direct gRPC call, where noted) is derived from one **common envelope** and a **type‑specific payload**. All examples are expressed as **JSON Schema 2020‑12** (the format already called‑out in the architecture) and are deliberately minimal so they can evolve without breaking consumers. Topic names follow the stream/topic layout already defined for Iggy.

---

## **1\. Common Event Envelope**

```
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AgentShellEventEnvelope‑v1",
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
    "event_id":   { "type": "string", "description": "ULID/UUID – idempotency key" },
    "type":       { "type": "string", "description": "Concrete event type (TurnEvent, StepEvent...)" },
    "spec_version": { "type": "string", "pattern": "^1\\.\\d+\\.\\d+$" },
    "timestamp":  { "type": "string", "format": "date-time" },
    "trace_id":   { "type": "string", "description": "OpenTelemetry trace/span root" },
    "tenant_id":  { "type": "string" },
    "session_id": { "type": "string" },
    "payload":    { "type": "object", "description": "Type‑specific payload" }
  }
}
```

*⬆ All subsequent schemas are only the `payload` block – they slot into the envelope above and are serialized as a single JSON object before publishing.*  
 *⬆ Keeping the envelope stable lets us version individual payloads without touching every consumer.*

---

## **2\. Turn Initiation — `TurnEvent`**

*Topic → `agent.turns.requests`*

```
{
  "title": "TurnEvent.v1",
  "type": "object",
  "required": ["turn_id", "user_message", "personality_id"],
  "properties": {
    "turn_id":        { "type": "string" },
    "user_message":   {
      "type": "object",
      "required": ["role", "content"],
      "properties": {
        "role":    { "const": "user" },
        "content": { "type": "string" }
      }
    },
    "personality_id": { "type": "string" },
    "metadata":       { "type": "object", "additionalProperties": true }
  }
}
```

### **Typical flow**

```
API Layer ─publish─► Iggy(turns.requests) ─┐
                                           ▼
                                   TurnManager
```

---

## **3\. Plan / Step Execution**

### **3.1 `StepEvent` (request)**

*Topic → `agent.steps.requests`*

```
{
  "title": "StepEvent.v1",
  "type": "object",
  "required": ["plan_id", "step_id", "step_index", "step_type", "instructions"],
  "properties": {
    "plan_id":     { "type": "string" },
    "step_id":     { "type": "string" },
    "step_index":  { "type": "integer", "minimum": 0 },
    "step_type":   { "enum": ["LLM_CALL", "TOOL_CALL", "MEMORY_OP", "EXTERNAL_API"] },
    "instructions":{ "type": "string" },
    "parameters":  { "type": "object", "additionalProperties": true }
  }
}
```

### **3.2 `StepResultEvent` (response)**

*Topic → `agent.steps.results`*

```
{
  "title": "StepResultEvent.v1",
  "type": "object",
  "required": ["step_id", "status"],
  "properties": {
    "step_id": { "type": "string" },
    "status":  { "enum": ["SUCCEEDED", "FAILED", "RETRYING", "CANCELLED"] },
    "output":  { "type": ["string", "object", "null"] },
    "error":   {
      "type": ["object", "null"],
      "properties": {
        "kind":  { "type": "string" },
        "detail":{ "type": "string" }
      }
    },
    "metrics": {
      "type": "object",
      "properties": {
        "latency_ms":      { "type": "number" },
        "prompt_tokens":   { "type": "integer" },
        "completion_tokens": { "type": "integer" },
        "cost_usd":        { "type": "number" }
      }
    }
  }
}
```

---

## **4\. Context / Memory Service Messages**

The **ContextManager** issues CRUD or semantic‑query operations to the **MemoryService**.  
 These calls are usually synchronous gRPC, but the same schema can travel over an Iggy topic (e.g., `agent.memory.ops`) for async bulk operations.

### **4.1 `MemoryRequest`**

```
{
  "title": "MemoryRequest.v1",
  "type": "object",
  "required": ["op_id", "operation", "namespace"],
  "properties": {
    "op_id":     { "type": "string" },
    "operation": {
      "enum": ["READ", "WRITE", "UPSERT", "DELETE", "QUERY_EMBEDDINGS"]
    },
    "namespace": { "type": "string", "description": "e.g. tenant/user/personality scope" },
    "keys":      { "type": "array", "items": { "type": "string" } },
    "data":      { "type": ["object","array","null"] },
    "query":     { "type": ["string","object","null"] }
  }
}
```

### **4.2 `MemoryResponse`**

```
{
  "title": "MemoryResponse.v1",
  "type": "object",
  "required": ["op_id", "status"],
  "properties": {
    "op_id":  { "type": "string" },
    "status": { "enum": ["OK", "ERROR"] },
    "data":   { "type": ["object","array","null"] },
    "error":  { "type": ["object","null"] }
  }
}
```

Memory operations are referenced in the step definitions and ContextManager responsibilities.

---

## **5\. Provider Adapter Layer Calls**

LLM / embedding / image generation requests are **synchronous gRPC** (Core Runtime ↔ ProviderAdapter), but the payloads mirror the envelope for audit re‑playability.

### **5.1 `ProviderRequest`**

```
{
  "title": "ProviderRequest.v1",
  "type": "object",
  "required": ["request_id", "provider", "model", "call_type"],
  "properties": {
    "request_id": { "type": "string" },
    "provider":   { "type": "string", "examples": ["openai","anthropic","grok"] },
    "model":      { "type": "string" },
    "call_type":  { "enum": ["COMPLETION","EMBEDDING","IMAGE","AUDIO"] },
    "parameters": { "type": "object", "additionalProperties": true },
    "payload":    { "type": "object", "description": "Prompt or other body" }
  }
}
```

### **5.2 `ProviderResponse`**

```
{
  "title": "ProviderResponse.v1",
  "type": "object",
  "required": ["request_id", "status"],
  "properties": {
    "request_id": { "type": "string" },
    "status":     { "enum": ["OK","ERROR"] },
    "output":     { "type": ["string","object","null"] },
    "usage": {
      "type": "object",
      "properties": {
        "prompt_tokens":     { "type": "integer" },
        "completion_tokens": { "type": "integer" },
        "cost_usd":          { "type": "number" }
      }
    },
    "error": { "type": ["object","null"] }
  }
}
```

These messages correspond to the `GeneratePlanLLMCall` and `ExecuteLLMCall` sequences shown in the Core Runtime diagram.

---

## **6\. Putting It Together**

| Interaction | Producer → Consumer(s) | Iggy Topic | Message Type |
| ----- | ----- | ----- | ----- |
| User request arrives | API Layer → TurnManager | `agent.turns.requests` | `TurnEvent` |
| Plan execution | PlanExecutor → StepProcessor(s) | `agent.steps.requests` | `StepEvent` |
| Step outcome | StepProcessor → PlanExecutor & Observability | `agent.steps.results` | `StepResultEvent` |
| Memory CRUD | ContextManager ↔ MemoryService (gRPC or `agent.memory.ops`) | `agent.memory.ops` | `MemoryRequest` / `MemoryResponse` |
| Provider call | Core Runtime ↔ ProviderAdapter (gRPC) | — (synchronous) | `ProviderRequest` / `ProviderResponse` |

All messages are **structured JSON** to keep Iggy topics self‑describing and easily consumable by downstream analytics or replay tools.

---

### **Next Steps**

1. **Field finalization & evolution strategy** – run these schemas through your API‑first review, assign semantic‑version rules, and publish in a shared `schemas/` repo.

2. **Code‑gen stubs** – generate Python dataclasses & Pydantic models (plus Protobuf if binary encoding is later required).

3. **Contract tests** – use Iggy’s SDK in a docker‑compose integration test to assert that a mock Core Runtime and MemoryService can round‑trip each message type without loss.

4. **Observability hooks** – embed OpenTelemetry spans keyed by `trace_id`, and emit StepResultEvent metrics to Prometheus as illustrated in the architecture.

These message definitions give the team a concrete artefact to build against while still leaving room for future provider‑specific or personality‑specific extensions.