import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import uuid
import json
from fastapi import HTTPException
from datetime import datetime, timezone # Added for mocking datetime objects

# Assuming server.py defines 'app' and 'event_publisher' is accessible for patching
# from server import app  # This might cause issues if server.py has side effects on import
# We will patch 'core.events.event_publisher' directly.

from core.events import EventEnvelope, TurnEventPayload # Removed EventType
from core.models import Message, Turn, Plan  # Removed TurnStatus & MessageRole

# It's better to create a fixture that provides the TestClient with a properly configured app.
# This involves ensuring lifespan events (startup/shutdown) are handled.
from server import app as actual_app # Import the FastAPI app instance from server.py

@pytest.fixture(scope="module")
def client() -> TestClient:
    # Ensure lifespan events are handled for the TestClient
    with TestClient(actual_app) as c:
        yield c

# Mock the global event_publisher instance from core.events directly if it's easier
# For now, patching where it's used in server.py or imported components is the approach.

@pytest.mark.asyncio
@patch('core.events.event_publisher.publish', new_callable=AsyncMock) # Patch the global publisher
async def test_create_turn_success(mock_publish: AsyncMock, client: TestClient):
    """
    Tests successful creation of a turn via POST /v1/turns,
    verifying that a TURN_START event is published with correct data.
    """
    request_payload = {
        "user_message": {"role": "user", "content": "Hello, agent!"},
        "personality_id": "test_personality_001",
        "session_id": "session_test_12345",
        "metadata": {"client_type": "test_client"},
        "turn_id": "custom_turn_id_provided" # Test with client-provided turn_id
    }
    headers = {"X-Request-ID": "test-trace-id-789"} # For trace_id

    response = client.post("/v1/turns", json=request_payload, headers=headers)

    assert response.status_code == 202
    response_json = response.json()
    assert response_json["message"] == "Turn processing initiated"
    assert response_json["turn_id"] == request_payload["turn_id"] # Ensure provided turn_id is used
    assert response_json["trace_id"] == headers["X-Request-ID"]

    mock_publish.assert_called_once()
    
    published_event_envelope: EventEnvelope = mock_publish.call_args[0][0]
    assert isinstance(published_event_envelope, EventEnvelope)
    assert published_event_envelope.type == "TURN_START" # Changed event_type to type
    assert published_event_envelope.trace_id == headers["X-Request-ID"]
    assert published_event_envelope.session_id == request_payload["session_id"]
    # EventEnvelope.event_id and timestamp are auto-generated, spec_version is fixed
    assert published_event_envelope.spec_version == "1.0.0"
    assert isinstance(uuid.UUID(published_event_envelope.event_id.replace("evt_", "")), uuid.UUID) # Check if valid UUID part

    published_payload: TurnEventPayload = published_event_envelope.payload
    assert isinstance(published_payload, TurnEventPayload)
    assert published_payload.turn_id == request_payload["turn_id"]
    
    # Assert specific fields of TurnEventPayload
    assert published_payload.user_message.role == request_payload["user_message"]["role"]
    assert published_payload.user_message.content == request_payload["user_message"]["content"]
    assert published_payload.personality_id == request_payload["personality_id"]
    assert published_payload.metadata == request_payload["metadata"]
    
    # Assert that fields made optional are None if not provided (or their default if set in model)
    assert published_payload.instructions is None 
    assert published_payload.parameters is None

# Test for when turn_id is NOT provided (should be generated)
@pytest.mark.asyncio
@patch('core.events.event_publisher.publish', new_callable=AsyncMock)
async def test_create_turn_success_generated_turn_id(mock_publish: AsyncMock, client: TestClient):
    request_payload = {
        "user_message": {"role": "user", "content": "Another hello!"},
        "personality_id": "test_perso_002",
        # No session_id or metadata for this test, ensure they are handled as None
    }
    # No X-Request-ID, so trace_id will be auto-generated

    response = client.post("/v1/turns", json=request_payload)

    assert response.status_code == 202
    response_json = response.json()
    assert "turn_id" in response_json
    generated_turn_id = response_json["turn_id"]
    assert generated_turn_id.startswith("turn_")
    assert "trace_id" in response_json # Trace ID is also returned in response now
    generated_trace_id = response_json["trace_id"]
    assert generated_trace_id.startswith("trace_")

    mock_publish.assert_called_once()
    published_event_envelope: EventEnvelope = mock_publish.call_args[0][0]
    assert published_event_envelope.type == "TURN_START" # Changed event_type to type
    assert published_event_envelope.trace_id == generated_trace_id # Ensure generated trace_id matches
    assert published_event_envelope.session_id is None # As it wasn't provided

    published_payload: TurnEventPayload = published_event_envelope.payload
    assert published_payload.turn_id == generated_turn_id
    assert published_payload.user_message.content == request_payload["user_message"]["content"]
    assert published_payload.personality_id == request_payload["personality_id"]
    assert published_payload.metadata is None # As it wasn't provided

@pytest.mark.asyncio
async def test_create_turn_malformed_json(client: TestClient):
    """Tests that a 400 error is returned for malformed JSON."""
    malformed_json_string = "{\"user_message\": {\"role\": \"user\", \"content\": \"Hi there\"}, \"personality_id\": \"test_perso_bad_json\" -- THIS IS BAD JSON"
    
    response = client.post(
        "/v1/turns", 
        content=malformed_json_string, 
        headers={"Content-Type": "application/json"}
    )
    
    # FastAPI typically returns 400 for JSON decoding errors if it gets to the Pydantic model directly
    # Or if our manual request.json() fails and we raise 400.
    assert response.status_code == 400 
    response_json = response.json()
    assert "detail" in response_json
    # The exact message might vary based on FastAPI version or our custom handling
    assert "Invalid JSON payload" in response_json["detail"] 

@pytest.mark.asyncio
@patch('core.events.event_publisher.publish', new_callable=AsyncMock)
async def test_create_turn_missing_required_fields(mock_publish: AsyncMock, client: TestClient):
    """Tests that a 422 error is returned for missing required fields."""
    
    # Test case 1: Missing user_message
    payload_missing_user_message = {
        "personality_id": "test_perso_003"
    }
    response = client.post("/v1/turns", json=payload_missing_user_message)
    assert response.status_code == 422
    assert "'user_message' (with role and content) is required" in response.json()["detail"]
    mock_publish.assert_not_called() # Ensure publisher not called on validation error

    mock_publish.reset_mock() # Reset mock for the next call

    # Test case 2: Missing personality_id
    payload_missing_personality_id = {
        "user_message": {"role": "user", "content": "Hello again"}
    }
    response = client.post("/v1/turns", json=payload_missing_personality_id)
    assert response.status_code == 422
    assert "'personality_id' (string) is required" in response.json()["detail"]
    mock_publish.assert_not_called()

    mock_publish.reset_mock()

    # Test case 3: Malformed user_message (e.g., missing role)
    payload_malformed_user_message = {
        "user_message": {"content": "Just content"}, # Missing role
        "personality_id": "test_perso_004"
    }
    response = client.post("/v1/turns", json=payload_malformed_user_message)
    assert response.status_code == 422
    assert "'user_message' (with role and content) is required" in response.json()["detail"]
    mock_publish.assert_not_called()

    mock_publish.reset_mock()

    # Test case 4: Invalid session_id type (e.g., not a string)
    payload_invalid_session_id = {
        "user_message": {"role": "user", "content": "Hello"},
        "personality_id": "test_perso_005",
        "session_id": 12345 # Integer instead of string
    }
    response = client.post("/v1/turns", json=payload_invalid_session_id)
    assert response.status_code == 422
    assert "Invalid 'session_id', must be a string if provided" in response.json()["detail"]
    mock_publish.assert_not_called()

    mock_publish.reset_mock()

    # Test case 5: Invalid metadata type (e.g., not a dict)
    payload_invalid_metadata = {
        "user_message": {"role": "user", "content": "Hello"},
        "personality_id": "test_perso_006",
        "metadata": "not_a_dictionary"
    }
    response = client.post("/v1/turns", json=payload_invalid_metadata)
    assert response.status_code == 422
    assert "Invalid 'metadata', must be a dictionary if provided" in response.json()["detail"]
    mock_publish.assert_not_called()

@pytest.mark.asyncio
@patch('core.events.event_publisher.publish', side_effect=Exception("Failed to publish event"))
async def test_create_turn_event_publisher_error(mock_publish: AsyncMock, client: TestClient):
    """Tests that a 500 error is returned when event_publisher.publish raises an error."""
    request_payload = {
        "user_message": {"role": "user", "content": "Hello error!"},
        "personality_id": "test_perso_error_case",
    }
    
    response = client.post("/v1/turns", json=request_payload)
    
    # Expect 500 when publish fails
    assert response.status_code == 500
    response_json = response.json()
    assert "detail" in response_json
    assert "Internal server error" in response_json["detail"]
    
    # Verify publisher was called but raised the exception
    mock_publish.assert_called_once()

@pytest.mark.asyncio
@patch('server.event_publisher.publish', new_callable=AsyncMock)
@patch('core.context.ContextManager.get_turn')
async def test_get_turn_status_success(mock_get_turn: AsyncMock, mock_publish: AsyncMock, client: TestClient):
    """Tests that the GET /v1/turns/{turn_id} endpoint works correctly."""
    turn_id = "turn_12345_success"
    
    # Expected data to be returned by the endpoint (after processing mock_turn_context)
    expected_created_at = datetime(2025, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    expected_updated_at = datetime(2025, 5, 13, 12, 5, 0, tzinfo=timezone.utc)
    expected_user_message_data = {"role": "user", "content": "Hello for success test"}
    expected_final_response_data = {"role": "assistant", "content": "Agent success response"}
    expected_plan_data = {"plan_id": "plan_success_789", "steps": [], "status": "COMPLETED"}

    expected_response_payload = {
        "turn_id": turn_id,
        "status": "COMPLETED", # This is now a direct string
        "user_message": expected_user_message_data,
        "final_response": expected_final_response_data,
        "created_at": expected_created_at.isoformat(),
        "updated_at": expected_updated_at.isoformat(),
        "session_id": "session_success_001",
        "metadata": {"test_case": "get_turn_status_success"},
        "metrics": {"llm_calls": 1, "total_tokens": 150},
        "plan": expected_plan_data
    }

    # Create a MagicMock that simulates a Turn object for the endpoint to process
    mock_turn_context = MagicMock(spec=Turn) 
    mock_turn_context.turn_id = turn_id
    mock_turn_context.status = "COMPLETED" # Status is a string
    
    mock_user_message = MagicMock(spec=Message)
    mock_user_message.model_dump.return_value = expected_user_message_data
    mock_turn_context.user_message = mock_user_message

    mock_final_response = MagicMock(spec=Message)
    mock_final_response.model_dump.return_value = expected_final_response_data
    mock_turn_context.final_response = mock_final_response
    
    mock_turn_context.created_at = expected_created_at
    mock_turn_context.updated_at = expected_updated_at
    
    mock_turn_context.session_id = expected_response_payload["session_id"]
    mock_turn_context.metadata = expected_response_payload["metadata"]
    mock_turn_context.metrics = expected_response_payload["metrics"]
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.model_dump.return_value = expected_plan_data
    mock_turn_context.plan = mock_plan
    
    mock_get_turn.return_value = mock_turn_context # context_manager.get_turn returns this mock

    response = client.get(f"/v1/turns/{turn_id}")

    assert response.status_code == 200
    assert response.json() == expected_response_payload

@pytest.mark.asyncio
@patch('server.event_publisher.publish', new_callable=AsyncMock)
@patch('core.context.ContextManager.get_turn', return_value=None)
async def test_get_turn_status_not_found(mock_get_turn: AsyncMock, mock_publish: AsyncMock, client: TestClient):
    """Tests that a 404 error is returned when the turn is not found."""
    turn_id = "nonexistent_turn_id"
    
    response = client.get(f"/v1/turns/{turn_id}")
    
    assert response.status_code == 404
    response_json = response.json()
    assert "detail" in response_json
    assert "Turn not found" in response_json["detail"]
    
    # Verify ContextManager.get_turn was called with the right turn_id
    mock_get_turn.assert_called_once_with(turn_id)

@pytest.mark.asyncio
@patch('server.event_publisher.publish', new_callable=AsyncMock)
@patch('core.context.ContextManager.get_turn', side_effect=Exception("Database error"))
async def test_get_turn_status_error(mock_get_turn: AsyncMock, mock_publish: AsyncMock, client: TestClient):
    """Tests that a 500 error is returned when getting turn status raises an error."""
    turn_id = "error_turn_id"
    
    response = client.get(f"/v1/turns/{turn_id}")
    
    assert response.status_code == 500
    response_json = response.json()
    assert "detail" in response_json
    assert "Internal server error" in response_json["detail"]
    
    # Verify ContextManager.get_turn was called with the right turn_id
    mock_get_turn.assert_called_once_with(turn_id) 