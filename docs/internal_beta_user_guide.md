# KFM Agent Shell - Internal Beta User Guide

## 1. Introduction

Welcome to the Kernel Function Machine (KFM) Agent Shell internal beta program! We're excited to have you help us test and refine this new platform.

**Purpose of this Beta:**
The primary goal of this internal beta is to gather your feedback on the core functionality, usability, and stability of the Agent Shell. Your insights will be invaluable in identifying areas for improvement before a wider release.

**What is the KFM Agent Shell?**
The KFM Agent Shell is an extensible framework designed to facilitate interactions with various Large Language Models (LLMs) through a consistent API. It allows users to define agent "personalities" that dictate behavior, LLM provider, and specific configurations. The system is built with modularity and observability in mind, aiming to provide a robust platform for developing and deploying AI-powered applications.

*(This description is based on architectural documents like `Task_001_Architecture.md` and inferred project goals.)*

## 2. Key Concepts

Understanding these core concepts will help you navigate the Agent Shell:

*   **Turn:** A single interaction cycle with an agent. It typically starts with a user message and results in an agent response or a series of actions. Each turn is uniquely identifiable by a `turn_id`.
*   **Personality:** A pre-defined configuration that determines an agent's behavior, including which LLM provider and model to use, system prompts, and other specific parameters. Each personality has a unique `personality_id`.
*   **Session (Optional):** A `session_id` can be provided to link multiple turns together, allowing the agent to maintain context and memory across a conversation. If not provided, each turn might be treated as a standalone interaction, depending on the underlying personality's design.
*   **Plan & Steps (Conceptual):** Internally, when a turn is processed, the Agent Shell may create a "plan" consisting of one or more "steps" to fulfill the user's request. While not directly manipulated by the user in this beta, understanding this can help interpret logs or more detailed turn status information.

## 3. Getting Started: Your First API Call

The primary way to interact with the Agent Shell during this beta is via its REST API.

*   **API Endpoint:** `POST /v1/turns`
*   **Authentication:** None required for the internal beta.
*   **Content-Type:** `application/json`

**Minimal Example Request (using cURL):**

```bash
curl -X POST -H "Content-Type: application/json" \
     -d '{
           "user_message": {"role": "user", "content": "Hello, agent!"},
           "personality_id": "default_echo" # Replace with an actual available personality
         }' \
     http://localhost:8000/v1/turns 
     # Assuming the server runs on localhost:8000
```

This request will initiate a new turn with the specified personality. You'll receive a response indicating that the turn processing has started.

## 4. API Reference: `/v1/turns` (POST)

This endpoint is used to initiate a new agent turn.

*   **HTTP Method:** `POST`
*   **Path:** `/v1/turns`
*   **Success Status Code:** `202 Accepted`

**Request Body (JSON):**

| Field            | Type   | Required | Description                                                                                                |
| ---------------- | ------ | -------- | ---------------------------------------------------------------------------------------------------------- |
| `user_message`   | object | Yes      | The user's input message. Must contain `role` (string, e.g., "user") and `content` (string).             |
| `personality_id` | string | Yes      | The identifier for the desired agent personality (e.g., "default_echo", "my_custom_gpt4_agent").        |
| `session_id`     | string | No       | An optional ID to link this turn to a specific session, enabling context persistence across multiple turns. |
| `turn_id`        | string | No       | An optional client-provided ID for the turn. If omitted, the server will generate one.                     |
| `metadata`       | object | No       | An optional dictionary for any client-specific metadata you want to associate with the turn.               |

**Headers:**

| Header         | Type   | Required | Description                                                                        |
| -------------- | ------ | -------- | ---------------------------------------------------------------------------------- |
| `X-Request-ID` | string | No       | An optional ID for tracing the request. If omitted, the server will generate one. |

**Success Response (202 Accepted):**

The server responds with a JSON object confirming that the turn processing has been initiated.

```json
{
  "message": "Turn processing initiated",
  "turn_id": "turn_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", 
  "trace_id": "trace_yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"
}
```

*   `turn_id`: The unique identifier for this turn. Use this ID to check the status later.
*   `trace_id`: The unique identifier for this request, useful for tracing and debugging.

**Error Responses:**

*   **`400 Bad Request`**: If the JSON payload is malformed.
    ```json
    { "detail": "Invalid JSON payload: <error_details>" }
    ```
*   **`422 Unprocessable Entity`**: If required fields are missing or have invalid types/values.
    ```json
    { "detail": "'user_message' (with role and content) is required." } 
    // or
    { "detail": "'personality_id' (string) is required." }
    // or
    { "detail": "Invalid 'session_id', must be a string if provided." }
    ```
*   **`500 Internal Server Error`**: If an unexpected error occurs on the server (e.g., failure to queue the event).
    ```json
    { "detail": "Internal server error: <error_details>" }
    ```

**Example cURL Request (Comprehensive):**

```bash
curl -X POST -H "Content-Type: application/json" \
     -H "X-Request-ID: client-trace-abc-123" \
     -d '{
           "user_message": {"role": "user", "content": "Tell me a joke."},
           "personality_id": "chatty_agent",
           "session_id": "my_chat_session_001",
           "turn_id": "my_custom_turn_id_456",
           "metadata": {"client_version": "1.2.3", "user_location": "testlab"}
         }' \
     http://localhost:8000/v1/turns
```

## 5. API Reference: `/v1/turns/{turn_id}` (GET)

This endpoint is used to retrieve the current status and details of a previously initiated turn.

*   **HTTP Method:** `GET`
*   **Path:** `/v1/turns/{turn_id}`
*   **Success Status Code:** `200 OK`

**Path Parameters:**

| Parameter | Type   | Required | Description                        |
| --------- | ------ | -------- | ---------------------------------- |
| `turn_id` | string | Yes      | The unique identifier of the turn. |

**Success Response (200 OK):**

The server responds with a JSON object containing the details of the turn. The exact fields may vary slightly based on the turn's state and the personality involved.

```json
{
  "turn_id": "turn_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "COMPLETED", // e.g., "PROCESSING", "COMPLETED", "ERROR", "PENDING"
  "user_message": {
    "role": "user",
    "content": "Tell me a joke."
  },
  "final_response": { // Present if status is COMPLETED and a response was generated
    "role": "assistant",
    "content": "Why don't scientists trust atoms? Because they make up everything!"
  },
  "created_at": "2025-05-13T10:00:00.000Z",
  "updated_at": "2025-05-13T10:00:05.123Z",
  "session_id": "my_chat_session_001",
  "metadata": {"client_version": "1.2.3", "user_location": "testlab"},
  "metrics": { // Example metrics, may vary
    "llm_calls": 1,
    "total_tokens": 50,
    "input_tokens": 20,
    "output_tokens": 30,
    "cost": 0.00015
  },
  "plan": { // Example plan structure, may vary
    "plan_id": "plan_zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
    "status": "COMPLETED",
    "steps": [
      {
        "step_id": "step_aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "status": "COMPLETED",
        "processor": "LLMStepProcessor",
        "result": "Successfully called LLM." 
      }
    ]
  }
}
```

**Possible `status` values:**
*   `PENDING`: The turn has been accepted but not yet started processing.
*   `PROCESSING`: The turn is actively being processed.
*   `COMPLETED`: The turn finished successfully, and `final_response` should be available.
*   `ERROR`: An error occurred during processing. Details might be in `plan` or logs.
*   *(Other personality-specific statuses might exist)*

**Error Responses:**

*   **`404 Not Found`**: If the specified `turn_id` does not exist.
    ```json
    { "detail": "Turn not found" }
    ```
*   **`500 Internal Server Error`**: If an unexpected error occurs on the server while retrieving or serializing turn data.
    ```json
    { "detail": "Internal server error while processing turn data: <error_details>" }
    ```

**Example cURL Request:**

```bash
curl -X GET http://localhost:8000/v1/turns/turn_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

## 6. Available Personalities

For the internal beta, the following personalities are available for testing:

*   **`default`** (Name: "Default", Version: 0.1.0)
    *   Description: A plain helpful assistant.
    *   This is the primary general-purpose personality available.
*   **`default_echo`**: A simple personality that echoes back your input. Useful for basic API connectivity testing. *(Note: This personality was mentioned as an example; confirm if it actually exists for the beta or should be removed/replaced by `default` for real testing.)*
*   **`basic_chat`**: (Hypothetical - to be confirmed) A personality configured for basic chat using a default LLM provider.
*   *(More personalities will be listed here as they become available for beta testing. You can inquire on the feedback channel for an updated list.)*

To discover personalities programmatically (if an endpoint becomes available in the future):
*   *(Details of a `/v1/personalities` GET endpoint would go here if it existed)*

For now, please refer to this guide or ask in the feedback channel for the current list.

## 7. Providing Feedback

Your feedback is crucial! Please report any bugs, issues, suggestions for improvement, or general comments through the following channels:

*   **Slack Channel:** `#kfm-beta-feedback` (Link: `[CONFIRM_SLACK_LINK_HERE]`)
*   **Email:** `kfm-beta@example.com` (Address: `[CONFIRM_EMAIL_ADDRESS_HERE]`)
*   **Issue Tracker:** (Link: `[CONFIRM_ISSUE_TRACKER_LINK_HERE]` if applicable)

When reporting bugs, please include:
*   Steps to reproduce the issue.
*   The `turn_id` and `trace_id` if applicable.
*   Expected behavior vs. actual behavior.
*   Any relevant error messages or logs.

## 8. Troubleshooting

**Common Issues:**

*   **Connection Refused:** Ensure the KFM Agent Shell server is running and accessible on the host and port you are targeting (default `http://localhost:8000`).
*   **`404 Not Found` for `/v1/turns` POST:** Double-check the URL path.
*   **`422 Unprocessable Entity`:** Carefully review your JSON request body against the requirements in Section 4. Ensure all required fields are present and correctly formatted.
*   **Personality Not Found:** If you receive an error related to an unknown `personality_id`, verify the ID against the list of available personalities.

**Interpreting Error Messages:**
The `detail` field in JSON error responses should provide specific information about the error. If you encounter persistent issues, please use the feedback channels, providing the full error message and context.

---
*Thank you for participating in the KFM Agent Shell Internal Beta!* 