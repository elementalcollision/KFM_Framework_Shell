# Defining Key Message Types and Structures for Agent Shell with Apache Iggy

The Agent Shell architecture is fundamentally event-driven, with Apache Iggy serving as the backbone for asynchronous, decoupled communication between all major system components. To ensure robust implementation, maintainability, and effective testing, it is crucial to define the primary message types, their structures, and their flow between components-especially those exchanged over Iggy streams. This report provides a detailed specification of the key message schemas, their rationale, and their role within the overall workflow, focusing on the following core domains:

\- Turn Initiation (\`TurnEvent\`)  
\- Step Execution (\`StepEvent\`, \`StepResultEvent\`)  
\- Context and Memory (\`UserSessionContext\`, \`MemoryOperationRequest\`, \`MemoryOperationResponse\`)  
\- Provider Calls (\`LLMRequest\`, \`LLMResponse\`, \`EmbeddingRequest\`, \`EmbeddingResponse\`, \`ModerationRequest\`, \`ModerationResponse\`)

The message definitions here are designed for JSON serialization, enabling schema validation and facilitating future evolution through versioning. Where appropriate, suggestions for schema evolution and compatibility are included, drawing on best practices from event-driven systems\[2\]\[3\]\[13\]\[18\]\[20\].

\#\# Overview of Event-Driven Messaging in Agent Shell

The Agent Shell's modular architecture relies on message-driven workflows to coordinate user interactions, planning, execution, memory access, and provider communication. Each significant state transition or action within the system is represented by a well-structured message, typically published to or consumed from a dedicated Iggy topic. This approach enables:

\- Loose coupling and horizontal scalability of components  
\- Clear contracts for inter-component communication  
\- Observability and traceability via correlation IDs  
\- Support for replay, auditing, and debugging

The message types are grouped according to the primary workflows described in the architecture: turn handling, plan and step execution, context/memory operations, and provider interactions.

\#\# Turn Initiation: The \`TurnEvent\`

\#\#\# Purpose and Flow

A \`TurnEvent\` represents the initiation of a new user interaction ("turn") with the system. It is published by the API Layer to the Iggy topic (e.g., \`agent.turns.requests\`) and consumed by the Core Runtime's \`TurnManager\`. This event encapsulates all information required to start processing a new turn, including user input, session identifiers, and optional settings.

\#\#\# Schema Definition

\`\`\`json  
{  
  "type": "object",  
  "title": "TurnEvent",  
  "description": "Represents the initiation of a new user interaction (turn) in the Agent Shell.",  
  "properties": {  
    "event\_type": { "type": "string", "const": "TurnEvent" },  
    "version": { "type": "string", "pattern": "^v\[0-9\]+$" },  
    "turn\_id": { "type": "string", "description": "Unique identifier for this turn." },  
    "trace\_id": { "type": "string", "description": "Correlation ID for tracing across components." },  
    "user\_id": { "type": "string", "description": "ID of the user initiating the turn." },  
    "session\_id": { "type": "string", "description": "Session identifier for ongoing conversations." },  
    "timestamp": { "type": "string", "format": "date-time" },  
    "input": {  
      "type": "object",  
      "properties": {  
        "input\_type": { "type": "string", "enum": \["text", "voice", "command"\] },  
        "content": { "type": "string", "description": "Raw user input." }  
      },  
      "required": \["input\_type", "content"\]  
    },  
    "personality\_id": { "type": "string", "description": "Optional: Personality to use for this turn." },  
    "settings": {  
      "type": "object",  
      "description": "Optional: Additional settings for this turn.",  
      "additionalProperties": true  
    }  
  },  
  "required": \["event\_type", "version", "turn\_id", "trace\_id", "user\_id", "session\_id", "timestamp", "input"\]  
}  
\`\`\`

\#\#\#\# Key Points

\- \*\*event\_type\*\* and \*\*version\*\* enable schema evolution and validation\[2\]\[13\]\[18\].  
\- \*\*trace\_id\*\* supports distributed tracing and observability.  
\- \*\*input\*\* allows for extensibility (e.g., supporting multi-modal input in the future).  
\- \*\*personality\_id\*\* and \*\*settings\*\* allow user customization per turn.

\#\#\# Example

\`\`\`json  
{  
  "event\_type": "TurnEvent",  
  "version": "v1",  
  "turn\_id": "turn\_001",  
  "trace\_id": "trace\_abc123",  
  "user\_id": "user\_42",  
  "session\_id": "sess\_987",  
  "timestamp": "2025-05-12T14:00:00Z",  
  "input": {  
    "input\_type": "text",  
    "content": "What's the weather today?"  
  },  
  "personality\_id": "weather\_bot\_v1",  
  "settings": {  
    "language": "en"  
  }  
}  
\`\`\`

\#\# Step Execution: \`StepEvent\` and \`StepResultEvent\`

\#\#\# Purpose and Flow

After a plan is generated for a turn, the \`PlanExecutor\` emits one or more \`StepEvent\` messages to the Iggy topic (e.g., \`agent.steps.requests\`). Each \`StepEvent\` represents an atomic action to be executed (LLM call, tool invocation, memory operation, etc.). The \`StepProcessor\` consumes these events, executes the step, and publishes a corresponding \`StepResultEvent\` (to \`agent.steps.results\`), which may trigger subsequent steps or signal completion.

\#\#\# \`StepEvent\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "StepEvent",  
  "description": "Represents an individual step to be executed as part of a plan.",  
  "properties": {  
    "event\_type": { "type": "string", "const": "StepEvent" },  
    "version": { "type": "string", "pattern": "^v\[0-9\]+$" },  
    "step\_id": { "type": "string", "description": "Unique identifier for this step." },  
    "plan\_id": { "type": "string", "description": "Identifier for the plan this step belongs to." },  
    "turn\_id": { "type": "string", "description": "Turn identifier for correlation." },  
    "trace\_id": { "type": "string" },  
    "step\_type": {  
      "type": "string",  
      "enum": \["llm\_call", "tool\_call", "memory\_read", "memory\_write", "api\_call"\]  
    },  
    "parameters": {  
      "type": "object",  
      "description": "Step-specific parameters (e.g., prompt, tool args, memory keys).",  
      "additionalProperties": true  
    },  
    "dependencies": {  
      "type": "array",  
      "items": { "type": "string" },  
      "description": "IDs of steps that must complete before this step executes."  
    },  
    "created\_at": { "type": "string", "format": "date-time" }  
  },  
  "required": \["event\_type", "version", "step\_id", "plan\_id", "turn\_id", "trace\_id", "step\_type", "parameters", "created\_at"\]  
}  
\`\`\`

\#\#\# \`StepResultEvent\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "StepResultEvent",  
  "description": "Represents the result of executing a step.",  
  "properties": {  
    "event\_type": { "type": "string", "const": "StepResultEvent" },  
    "version": { "type": "string", "pattern": "^v\[0-9\]+$" },  
    "step\_id": { "type": "string" },  
    "plan\_id": { "type": "string" },  
    "turn\_id": { "type": "string" },  
    "trace\_id": { "type": "string" },  
    "status": { "type": "string", "enum": \["success", "failure", "partial", "skipped"\] },  
    "result": {  
      "type": "object",  
      "description": "Step-specific result data (e.g., LLM output, tool result, memory value).",  
      "additionalProperties": true  
    },  
    "error": {  
      "type": "object",  
      "description": "Error details if status is failure.",  
      "properties": {  
        "code": { "type": "string" },  
        "message": { "type": "string" },  
        "details": { "type": "object", "additionalProperties": true }  
      },  
      "required": \["code", "message"\],  
      "nullable": true  
    },  
    "completed\_at": { "type": "string", "format": "date-time" }  
  },  
  "required": \["event\_type", "version", "step\_id", "plan\_id", "turn\_id", "trace\_id", "status", "result", "completed\_at"\]  
}  
\`\`\`

\#\#\#\# Key Points

\- Both events include \*\*event\_type\*\*, \*\*version\*\*, and correlation IDs for traceability.  
\- \*\*parameters\*\* and \*\*result\*\* are open-ended to support extensibility as new step types are introduced.  
\- \*\*dependencies\*\* enables execution of steps in a DAG or linear sequence.  
\- \*\*status\*\* and \*\*error\*\* fields in \`StepResultEvent\` support robust error handling and retries.

\#\#\# Example

\#\#\#\# StepEvent (LLM Call)

\`\`\`json  
{  
  "event\_type": "StepEvent",  
  "version": "v1",  
  "step\_id": "step\_123",  
  "plan\_id": "plan\_456",  
  "turn\_id": "turn\_001",  
  "trace\_id": "trace\_abc123",  
  "step\_type": "llm\_call",  
  "parameters": {  
    "prompt": "Summarize the following text...",  
    "model": "gpt-4o",  
    "temperature": 0.7  
  },  
  "dependencies": \[\],  
  "created\_at": "2025-05-12T14:01:00Z"  
}  
\`\`\`

\#\#\#\# StepResultEvent (Success)

\`\`\`json  
{  
  "event\_type": "StepResultEvent",  
  "version": "v1",  
  "step\_id": "step\_123",  
  "plan\_id": "plan\_456",  
  "turn\_id": "turn\_001",  
  "trace\_id": "trace\_abc123",  
  "status": "success",  
  "result": {  
    "output\_text": "The text is about...",  
    "tokens\_used": 120  
  },  
  "error": null,  
  "completed\_at": "2025-05-12T14:01:05Z"  
}  
\`\`\`

\#\#\#\# StepResultEvent (Failure)

\`\`\`json  
{  
  "event\_type": "StepResultEvent",  
  "version": "v1",  
  "step\_id": "step\_124",  
  "plan\_id": "plan\_456",  
  "turn\_id": "turn\_001",  
  "trace\_id": "trace\_abc123",  
  "status": "failure",  
  "result": {},  
  "error": {  
    "code": "TOOL\_NOT\_FOUND",  
    "message": "Requested tool 'get\_weather' not found in personality.",  
    "details": {}  
  },  
  "completed\_at": "2025-05-12T14:01:07Z"  
}  
\`\`\`

\#\# Context and Memory: \`UserSessionContext\`, \`MemoryOperationRequest\`, \`MemoryOperationResponse\`

\#\#\# Purpose and Flow

Context and memory operations underpin the agent's ability to maintain conversation history, user preferences, and knowledge base access. The \`ContextManager\` and \`MemoryService\` exchange structured data for CRUD operations on session context and knowledge retrieval. These messages may be exchanged directly (e.g., via RPC) or over Iggy topics for asynchronous workflows, especially for long-running knowledge queries or background context updates.

\#\#\# \`UserSessionContext\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "UserSessionContext",  
  "description": "Represents the persistent state for a user session.",  
  "properties": {  
    "user\_id": { "type": "string" },  
    "session\_id": { "type": "string" },  
    "conversation\_history": {  
      "type": "array",  
      "items": {  
        "type": "object",  
        "properties": {  
          "role": { "type": "string", "enum": \["user", "assistant"\] },  
          "content": { "type": "string" },  
          "timestamp": { "type": "string", "format": "date-time" }  
        },  
        "required": \["role", "content", "timestamp"\]  
      }  
    },  
    "user\_preferences": {  
      "type": "object",  
      "additionalProperties": true  
    },  
    "last\_accessed": { "type": "string", "format": "date-time" }  
  },  
  "required": \["user\_id", "session\_id", "conversation\_history", "user\_preferences", "last\_accessed"\]  
}  
\`\`\`

\#\#\# \`MemoryOperationRequest\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "MemoryOperationRequest",  
  "description": "Request to perform a memory operation (CRUD or RAG query).",  
  "properties": {  
    "operation\_id": { "type": "string" },  
    "operation\_type": {  
      "type": "string",  
      "enum": \["get\_context", "save\_context", "add\_knowledge", "search\_knowledge"\]  
    },  
    "user\_id": { "type": "string" },  
    "session\_id": { "type": "string" },  
    "payload": {  
      "type": "object",  
      "description": "Operation-specific payload (e.g., context data, search query).",  
      "additionalProperties": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["operation\_id", "operation\_type", "user\_id", "session\_id", "payload", "timestamp"\]  
}  
\`\`\`

\#\#\# \`MemoryOperationResponse\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "MemoryOperationResponse",  
  "description": "Response from a memory operation.",  
  "properties": {  
    "operation\_id": { "type": "string" },  
    "status": { "type": "string", "enum": \["success", "failure"\] },  
    "result": {  
      "type": "object",  
      "description": "Operation-specific result (e.g., context data, search results).",  
      "additionalProperties": true  
    },  
    "error": {  
      "type": "object",  
      "properties": {  
        "code": { "type": "string" },  
        "message": { "type": "string" },  
        "details": { "type": "object", "additionalProperties": true }  
      },  
      "required": \["code", "message"\],  
      "nullable": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["operation\_id", "status", "result", "timestamp"\]  
}  
\`\`\`

\#\#\#\# Key Points

\- \*\*operation\_id\*\* allows correlation between requests and responses.  
\- \*\*operation\_type\*\* and \*\*payload\*\* support extensibility for new memory operations.  
\- \*\*result\*\* is open-ended for flexibility (e.g., can return full context, search results, etc.).  
\- These schemas support both synchronous and asynchronous (event-driven) memory workflows.

\#\#\# Example

\#\#\#\# MemoryOperationRequest (RAG Search)

\`\`\`json  
{  
  "operation\_id": "op\_789",  
  "operation\_type": "search\_knowledge",  
  "user\_id": "user\_42",  
  "session\_id": "sess\_987",  
  "payload": {  
    "query": "What is the capital of France?",  
    "personality\_id": "geo\_bot\_v1",  
    "top\_k": 5  
  },  
  "timestamp": "2025-05-12T14:02:00Z"  
}  
\`\`\`

\#\#\#\# MemoryOperationResponse (RAG Search Result)

\`\`\`json  
{  
  "operation\_id": "op\_789",  
  "status": "success",  
  "result": {  
    "hits": \[  
      {  
        "document\_id": "doc\_001",  
        "chunk\_id": "chunk\_01",  
        "text": "Paris is the capital of France.",  
        "score": 0.98  
      }  
    \]  
  },  
  "error": null,  
  "timestamp": "2025-05-12T14:02:01Z"  
}  
\`\`\`

\#\# Provider Calls: \`LLMRequest\`, \`LLMResponse\`, \`EmbeddingRequest\`, \`EmbeddingResponse\`, \`ModerationRequest\`, \`ModerationResponse\`

\#\#\# Purpose and Flow

The Provider Adapter Layer abstracts communication with external LLM APIs (e.g., OpenAI, Anthropic). The Core Runtime (\`PlanExecutor\`, \`StepProcessor\`) issues requests for text generation, embedding, or moderation, and receives standardized responses. These interactions may occur over direct calls within a process, but for testability and observability, can also be modeled as messages (especially in distributed deployments).

\#\#\# \`LLMRequest\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "LLMRequest",  
  "description": "Request to generate text from an LLM provider.",  
  "properties": {  
    "request\_id": { "type": "string" },  
    "trace\_id": { "type": "string" },  
    "turn\_id": { "type": "string" },  
    "step\_id": { "type": "string" },  
    "provider": { "type": "string" },  
    "model": { "type": "string" },  
    "prompt": { "type": "string" },  
    "parameters": {  
      "type": "object",  
      "properties": {  
        "temperature": { "type": "number" },  
        "max\_tokens": { "type": "integer" },  
        "top\_p": { "type": "number" },  
        "stream": { "type": "boolean" }  
      },  
      "additionalProperties": true  
    },  
    "context": {  
      "type": "object",  
      "description": "Optional: Additional context for the provider (e.g., conversation history, user profile).",  
      "additionalProperties": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["request\_id", "trace\_id", "turn\_id", "step\_id", "provider", "model", "prompt", "parameters", "timestamp"\]  
}  
\`\`\`

\#\#\# \`LLMResponse\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "LLMResponse",  
  "description": "Response from an LLM provider.",  
  "properties": {  
    "request\_id": { "type": "string" },  
    "trace\_id": { "type": "string" },  
    "turn\_id": { "type": "string" },  
    "step\_id": { "type": "string" },  
    "status": { "type": "string", "enum": \["completed", "failed", "in\_progress", "incomplete"\] },  
    "output": {  
      "type": "object",  
      "properties": {  
        "text": { "type": "string" },  
        "tokens\_used": { "type": "integer" },  
        "model\_used": { "type": "string" },  
        "finish\_reason": { "type": "string" }  
      },  
      "required": \["text"\]  
    },  
    "error": {  
      "type": "object",  
      "properties": {  
        "code": { "type": "string" },  
        "message": { "type": "string" },  
        "details": { "type": "object", "additionalProperties": true }  
      },  
      "required": \["code", "message"\],  
      "nullable": true  
    },  
    "provider\_raw\_response": {  
      "type": "object",  
      "description": "Optional: Raw response from the provider for debugging.",  
      "additionalProperties": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["request\_id", "trace\_id", "turn\_id", "step\_id", "status", "output", "timestamp"\]  
}  
\`\`\`

\#\#\# \`EmbeddingRequest\` and \`EmbeddingResponse\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "EmbeddingRequest",  
  "description": "Request to generate embeddings for text chunks.",  
  "properties": {  
    "request\_id": { "type": "string" },  
    "trace\_id": { "type": "string" },  
    "provider": { "type": "string" },  
    "model": { "type": "string" },  
    "text\_chunks": {  
      "type": "array",  
      "items": { "type": "string" }  
    },  
    "parameters": {  
      "type": "object",  
      "additionalProperties": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["request\_id", "trace\_id", "provider", "model", "text\_chunks", "parameters", "timestamp"\]  
}  
\`\`\`

\`\`\`json  
{  
  "type": "object",  
  "title": "EmbeddingResponse",  
  "description": "Response containing embeddings for text chunks.",  
  "properties": {  
    "request\_id": { "type": "string" },  
    "trace\_id": { "type": "string" },  
    "status": { "type": "string", "enum": \["completed", "failed"\] },  
    "embeddings": {  
      "type": "array",  
      "items": {  
        "type": "object",  
        "properties": {  
          "text": { "type": "string" },  
          "embedding": { "type": "array", "items": { "type": "number" } }  
        },  
        "required": \["text", "embedding"\]  
      }  
    },  
    "error": {  
      "type": "object",  
      "properties": {  
        "code": { "type": "string" },  
        "message": { "type": "string" },  
        "details": { "type": "object", "additionalProperties": true }  
      },  
      "required": \["code", "message"\],  
      "nullable": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["request\_id", "trace\_id", "status", "embeddings", "timestamp"\]  
}  
\`\`\`

\#\#\# \`ModerationRequest\` and \`ModerationResponse\` Schema

\`\`\`json  
{  
  "type": "object",  
  "title": "ModerationRequest",  
  "description": "Request to moderate a text input.",  
  "properties": {  
    "request\_id": { "type": "string" },  
    "trace\_id": { "type": "string" },  
    "provider": { "type": "string" },  
    "model": { "type": "string" },  
    "text": { "type": "string" },  
    "parameters": {  
      "type": "object",  
      "additionalProperties": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["request\_id", "trace\_id", "provider", "model", "text", "parameters", "timestamp"\]  
}  
\`\`\`

\`\`\`json  
{  
  "type": "object",  
  "title": "ModerationResponse",  
  "description": "Response from moderation API.",  
  "properties": {  
    "request\_id": { "type": "string" },  
    "trace\_id": { "type": "string" },  
    "status": { "type": "string", "enum": \["completed", "failed"\] },  
    "moderation\_flags": {  
      "type": "object",  
      "description": "Flags indicating moderation results.",  
      "additionalProperties": true  
    },  
    "scores": {  
      "type": "object",  
      "description": "Optional: Scores or probabilities for each flag.",  
      "additionalProperties": true  
    },  
    "error": {  
      "type": "object",  
      "properties": {  
        "code": { "type": "string" },  
        "message": { "type": "string" },  
        "details": { "type": "object", "additionalProperties": true }  
      },  
      "required": \["code", "message"\],  
      "nullable": true  
    },  
    "timestamp": { "type": "string", "format": "date-time" }  
  },  
  "required": \["request\_id", "trace\_id", "status", "moderation\_flags", "scores", "timestamp"\]  
}  
\`\`\`

\#\#\#\# Key Points

\- All provider call schemas include \*\*request\_id\*\*, \*\*trace\_id\*\*, and relevant IDs for traceability.  
\- \*\*parameters\*\* fields are open-ended for model- or provider-specific options.  
\- \*\*output\*\* and \*\*error\*\* fields are standardized for uniform handling across providers.  
\- \*\*provider\_raw\_response\*\* in \`LLMResponse\` supports debugging and future-proofing.

\#\#\# Example

\#\#\#\# LLMRequest

\`\`\`json  
{  
  "request\_id": "req\_001",  
  "trace\_id": "trace\_abc123",  
  "turn\_id": "turn\_001",  
  "step\_id": "step\_123",  
  "provider": "openai",  
  "model": "gpt-4o",  
  "prompt": "Tell me a joke.",  
  "parameters": {  
    "temperature": 0.8,  
    "max\_tokens": 50  
  },  
  "context": {  
    "conversation\_history": \[  
      {  
        "role": "user",  
        "content": "Hello\!",  
        "timestamp": "2025-05-12T14:00:00Z"  
      }  
    \]  
  },  
  "timestamp": "2025-05-12T14:01:00Z"  
}  
\`\`\`

\#\#\#\# LLMResponse

\`\`\`json  
{  
  "request\_id": "req\_001",  
  "trace\_id": "trace\_abc123",  
  "turn\_id": "turn\_001",  
  "step\_id": "step\_123",  
  "status": "completed",  
  "output": {  
    "text": "Why did the chicken cross the road? To get to the other side\!",  
    "tokens\_used": 20,  
    "model\_used": "gpt-4o",  
    "finish\_reason": "stop\_sequence"  
  },  
  "error": null,  
  "provider\_raw\_response": {},  
  "timestamp": "2025-05-12T14:01:01Z"  
}  
\`\`\`

\#\# Message Versioning and Schema Evolution

To support backward- and forward-compatible changes, each message includes a \*\*version\*\* or \*\*event\_type\*\* field. This enables:

\- Consumers to select the correct schema for validation and deserialization\[2\]\[3\]\[13\]\[18\].  
\- Producers to evolve message formats without breaking downstream consumers.  
\- Support for upcasting/downcasting of messages if needed in the future.

For example, if a new field is added to \`StepEvent\`, consumers using the \`v1\` schema can safely ignore it, while those supporting \`v2\` can process the new field.

\#\# Message Routing and Topic Structure in Iggy

Each message type is routed via a dedicated Iggy topic, as outlined in the architecture:

| Message Type         | Iggy Topic                | Producer Component     | Consumer Component(s)    |  
|----------------------|--------------------------|-----------------------|--------------------------|  
| TurnEvent            | agent.turns.requests     | API Layer             | TurnManager              |  
| StepEvent            | agent.steps.requests     | PlanExecutor          | StepProcessor            |  
| StepResultEvent      | agent.steps.results      | StepProcessor         | PlanExecutor, TurnManager|  
| MemoryOperation\*     | agent.memory.operations  | ContextManager        | MemoryService            |  
| MemoryOperation\*     | agent.memory.responses   | MemoryService         | ContextManager           |  
| LLMRequest           | agent.providers.requests | StepProcessor         | ProviderAdapterLayer     |  
| LLMResponse          | agent.providers.responses| ProviderAdapterLayer  | StepProcessor            |

This structure enables parallelism and scalability, as multiple consumers can process events in a consumer group, and partitioning can be done by user/session/turn for load balancing\[7\]\[10\]\[19\].

\#\# Observability and Correlation

Every message includes \*\*trace\_id\*\*, \*\*turn\_id\*\*, and other identifiers, supporting distributed tracing and observability. This allows for:

\- End-to-end tracking of user requests across turns, plans, steps, and provider calls.  
\- Correlation of logs, metrics, and traces for debugging and performance analysis.  
\- Auditing and replay of events for compliance and testing.

\#\# Implementation and Testing Considerations

\- \*\*Schema Validation\*\*: All messages should be validated against their JSON Schema before publishing or processing, ensuring contract adherence\[13\]\[18\]\[20\].  
\- \*\*Mocking and Replay\*\*: Well-defined message schemas enable mocking of downstream components and replay of recorded events for testing.  
\- \*\*Extensibility\*\*: Open-ended fields (e.g., \`parameters\`, \`result\`) allow for future step types and provider features without breaking existing consumers.  
\- \*\*Error Handling\*\*: Standardized error fields in result and response messages support uniform error handling and retries.

\#\# Conclusion

Defining and standardizing the key message types and their schemas is foundational for the Agent Shell's event-driven architecture. The proposed message structures for turn initiation, step execution, context/memory operations, and provider calls provide clear contracts for implementation, facilitate robust testing, and ensure the system's scalability and maintainability. These schemas, combined with careful versioning and topic management in Apache Iggy, will enable the Agent Shell to deliver on its goals of modularity, provider agnosticism, and high performance.

As the architecture evolves, these schemas should be maintained as living documents, with changes managed through versioned updates and coordinated rollouts across producer and consumer components. This approach will ensure the Agent Shell remains robust, extensible, and easy to operate in production environments.

Sources  
\[1\] architecture\_document.md https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/64137834/13ff178f-aed0-4788-915c-55f273b718f4/architecture\_document.md  
\[2\] Simple patterns for events schema versioning \- Event-Driven.io https://event-driven.io/en/simple\_events\_versioning\_patterns/  
\[3\] Event sourcing with kafka \- confluent schema registry \- Stack Overflow https://stackoverflow.com/questions/66983382/event-sourcing-with-kafka  
\[4\] Learn About Google Event Schema Markup | Documentation https://developers.google.com/search/docs/appearance/structured-data/event  
\[5\] API Reference \- OpenAI Platform https://platform.openai.com/docs/api-reference/chat  
\[6\] OpenAI API Reference Docs https://platform.openai.com/docs/api-reference/introduction  
\[7\] How can I get LLM to only respond in JSON strings? \- Stack Overflow https://stackoverflow.com/questions/77407632/how-can-i-get-llm-to-only-respond-in-json-strings  
\[8\] conversations.history method \- Slack API https://api.slack.com/methods/conversations.history  
\[9\] Control agent session context \- Amazon Bedrock https://docs.aws.amazon.com/bedrock/latest/userguide/agents-session-state.html  
\[10\] Event-driven architecture: Understanding the essential benefits https://www.redhat.com/en/blog/event-driven-architecture-essentials  
\[11\] ChatGPT chat completions API \- OpenAI Platform https://platform.openai.com/docs/guides/text-generation/chat-completions-api  
\[12\] /conversations.history \- Slack Web API \- Apidog https://apidog.com/apidoc/project-347399/api-3545273  
\[13\] JSON Schema for Events \- Stack Overflow https://stackoverflow.com/questions/73453620/json-schema-for-events  
\[14\] OpenAI Doc \- Structured Outputs https://platform.openai.com/docs/guides/structured-outputs  
\[15\] I mapped the JSON structure of a conversation dictionary : r/OpenAI https://www.reddit.com/r/OpenAI/comments/18tw934/i\_mapped\_the\_json\_structure\_of\_a\_conversation/  
\[16\] Wikimedia's Event Data Platform – JSON & Event Schemas https://techblog.wikimedia.org/2020/09/17/wikimedias-event-data-platform-json-event-schemas/  
\[17\] Chat Completions Guide \- OpenAI Platform https://platform.openai.com/docs/guides/chat-completions  
\[18\] Creating an event schema in Amazon EventBridge https://docs.aws.amazon.com/en\_us/eventbridge/latest/userguide/eb-schema-create.html  
\[19\] Chat Completions API Schema \- Deep Java Library https://docs.djl.ai/master/docs/serving/serving/docs/lmi/user\_guides/chat\_input\_output\_schema.html  
\[20\] JSON Schema examples https://json-schema.org/learn/json-schema-examples  
\[21\] Work with chat completion models \- Azure OpenAI Service https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/chatgpt  
\[22\] Event Design and Event Streams Best Practices \- Confluent Developer https://developer.confluent.io/courses/event-design/best-practices/  
\[23\] Event \- Schema.org Type https://schema.org/Event  
\[24\] Payload schema | AsyncAPI Initiative for event-driven APIs https://www.asyncapi.com/docs/concepts/asyncapi-document/define-payload  
\[25\] Best Practices for Confluent Schema Registry https://www.confluent.io/blog/best-practices-for-confluent-schema-registry/  
\[26\] Creating an event schema in Amazon EventBridge https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-schema-create.html  
\[27\] Validate using an Json schema when streaming events using Event ... https://learn.microsoft.com/en-gb/answers/questions/1569647/validate-using-an-json-schema-when-streaming-event  
\[28\] Best practices for implementing event-driven architectures in ... \- AWS https://aws.amazon.com/blogs/architecture/best-practices-for-implementing-event-driven-architectures-in-your-organization/  
\[29\] Miscellaneous Examples \- JSON Schema https://json-schema.org/learn/miscellaneous-examples  
\[30\] Event sourcing with Kafka: A practical example \- Tinybird https://www.tinybird.co/blog-posts/event-sourcing-with-kafka  
\[31\] Appendix G. Event Representation: JSON Events \- EsperTech http://esper.espertech.com/release-8.3.0/reference-esper/html/appendix\_eventrepjson.html  
\[32\] What are Your Best Practices for Reporting on Schema Evolution? https://www.reddit.com/r/dataengineering/comments/1f1uvkd/what\_are\_your\_best\_practices\_for\_reporting\_on/  
\[33\] Sample JSON Schema \- Informatica Documentation https://docs.informatica.com/data-integration/b2b-data-transformation/10-5/user-guide/wizard-input-and-output-formats/json/sample-json-schema.html  
\[34\] How to Achieve Dynamic Response Schema \- API https://community.openai.com/t/how-to-achieve-dynamic-response-schema/914019  
\[35\] Data extraction: The many ways to get LLMs to spit JSON content https://glaforge.dev/posts/2024/11/18/data-extraction-the-many-ways-to-get-llms-to-spit-json-content/  
\[36\] Official documentation for supported schemas for \`response\_format ... https://community.openai.com/t/official-documentation-for-supported-schemas-for-response-format-parameter-in-calls-to-client-beta-chats-completions-parse/932422  
\[37\] Introducing Structured Outputs in the API \- OpenAI https://openai.com/index/introducing-structured-outputs-in-the-api/  
\[38\] imaurer/awesome-llm-json: Resource list for generating ... \- GitHub https://github.com/imaurer/awesome-llm-json  
\[39\] Structure output, JSON schema. Completion API \- Bugs https://community.openai.com/t/structure-output-json-schema-completion-api/976607  
\[40\] API response is not JSON parsable despite specified response format https://community.openai.com/t/api-response-is-not-json-parsable-despite-specified-response-format/1014311  
\[41\] Generating JSON with self hosted LLM : r/LocalLLaMA \- Reddit https://www.reddit.com/r/LocalLLaMA/comments/16e8qa0/generating\_json\_with\_self\_hosted\_llm/  
\[42\] Structured Outputs with Batch Processing \- OpenAI Developer Forum https://community.openai.com/t/structured-outputs-with-batch-processing/911076  
\[43\] Dynamic Json schema output format for assistant \- API https://community.openai.com/t/dynamic-json-schema-output-format-for-assistant/975365  
\[44\] Make JSON output more likely \- API \- OpenAI Developer Community https://community.openai.com/t/make-json-output-more-likely/718590  
\[45\] How to pass prompt to the chat.completions.create \- API https://community.openai.com/t/how-to-pass-prompt-to-the-chat-completions-create/592629  
\[46\] Referring to the function-call JSON Schema in a follow-up ... https://community.openai.com/t/referring-to-the-function-call-json-schema-in-a-follow-up-completions-message-thread/710637  
\[47\] Manage User Session Attributes and Claims Mapping \- Cloudentity https://cloudentity.com/developers/howtos/authentication/user-session-management/  
\[48\] How we run Open Community Working Meetings, a retro \#279 https://github.com/orgs/json-schema-org/discussions/279  
\[49\] What is the best way to include the user in a session to all children ... https://www.reddit.com/r/nextjs/comments/1b2hnqc/what\_is\_the\_best\_way\_to\_include\_the\_user\_in\_a/  
\[50\] Annotations \- JSON Schema https://json-schema.org/understanding-json-schema/reference/annotations  
\[51\] Using Application Contexts to Retrieve User Information https://docs.oracle.com/en/database/oracle/oracle-database/19/dbseg/using-application-contexts-to-retrieve-user-information.html  
\[52\] JSON schema validation https://docs.oracle.com/cd/E55956\_01/doc.11123/user\_guide/content/content\_schema\_json.html  
\[53\] SESSION\_CONTEXT (Transact-SQL) \- SQL Server \- Learn Microsoft https://learn.microsoft.com/en-us/sql/t-sql/functions/session-context-transact-sql?view=sql-server-ver16  
\[54\] How to add http session-management tag in application context in ... https://stackoverflow.com/questions/35555229/how-to-add-http-session-management-tag-in-application-context-in-spring  
\[55\] Solved: Setting Session Context \- Microsoft Fabric Community https://community.fabric.microsoft.com/t5/Developer/Setting-Session-Context/m-p/747032  
\[56\] Application Insights \- Tracking user and session across schemas https://stackoverflow.com/questions/52672214/application-insights-tracking-user-and-session-across-schemas  
\[57\] ALTER SESSION SET CURRENT\_SCHEMA \- Ask TOM https://asktom.oracle.com/pls/apex/asktom.search%3Ftag=alter-session-set-current-schema  
\[58\] Decoding Exported Data by Parsing conversations.json and/or chat ... https://community.openai.com/t/decoding-exported-data-by-parsing-conversations-json-and-or-chat-html/403144  
\[59\] /conversations.history \- Slack Web API \- Apidog https://apidog.com/apidoc/docs-site/347399/api-3545273  
\[60\] Conversation \- Intercom Developers https://developers.intercom.com/docs/references/rest-api/api.intercom.io/conversations/conversation  
\[61\] Session context in Notebooks | Snowflake Documentation https://docs.snowflake.com/en/user-guide/ui-snowsight/notebooks-sessions

