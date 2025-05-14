import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any, Optional

# Framework imports
from core.config import (
    AppConfig, CoreRuntimeConfig, ProviderConfig, LLMConfig, EmbeddingConfig, 
    PersonalityConfig, ToolDefinition, PlanningConfig, ResponseConfig, MemoryConfigPersonality, OpenAIProviderConfig
)
from core.runtime import StepProcessor, TurnContext
from core.schema import Message, StepEventPayload
from core.events import EventEnvelope, StepResultEventPayload, EventPublisherSubscriber, EventType
from core.context import ContextManager
from memory.manager import MemoryManager
from providers.factory import ProviderFactory
from core.personality import PersonalityPackManager
from core.errors import ToolExecutionError, ToolNotFoundError, ConfigurationError # Assuming a specific error type

# --- Fixtures ---

@pytest.fixture
def app_config_fixture() -> AppConfig:
    """Basic AppConfig for personality integration tests."""
    # A minimal AppConfig, can be expanded if tests need more specific settings
    return AppConfig(
        core_runtime=CoreRuntimeConfig(default_provider="openai"),
        providers={
            "openai": ProviderConfig(
                type="openai",
                config=OpenAIProviderConfig(
                    api_key="test_key_openai",
                    llm=LLMConfig(model="gpt-3.5-turbo")
                )
            )
        }
    )

@pytest.fixture
def mock_context_manager() -> MagicMock:
    mock = MagicMock(spec=ContextManager)
    mock.get_turn_context = AsyncMock()
    mock.get_step_context = AsyncMock(return_value={})
    mock.update_step_context = AsyncMock()
    return mock

@pytest.fixture
def mock_event_publisher() -> MagicMock:
    mock = MagicMock(spec=EventPublisherSubscriber)
    mock.publish = AsyncMock()
    return mock

@pytest.fixture
def mock_memory_manager() -> MagicMock:
    return MagicMock(spec=MemoryManager)

@pytest.fixture
def mock_provider_factory() -> MagicMock:
    return MagicMock(spec=ProviderFactory)

@pytest.fixture
def mock_personality_pack_manager() -> MagicMock:
    mock = MagicMock(spec=PersonalityPackManager)
    mock.get_personality = AsyncMock() # Behavior configured per test
    mock.execute_tool = AsyncMock()    # Behavior configured per test
    return mock

@pytest.fixture
def step_processor_for_personality_tests(
    app_config_fixture: AppConfig,
    mock_provider_factory: MagicMock,
    mock_context_manager: MagicMock,
    mock_event_publisher: MagicMock,
    mock_personality_pack_manager: MagicMock,
    mock_memory_manager: MagicMock
) -> StepProcessor:
    """Provides a StepProcessor instance with mocked dependencies for personality tests."""
    return StepProcessor(
        app_config=app_config_fixture,
        provider_factory=mock_provider_factory,
        context_manager=mock_context_manager,
        event_publisher=mock_event_publisher,
        personality_manager=mock_personality_pack_manager,
        memory_manager=mock_memory_manager
    )

# --- Test Cases ---

@pytest.mark.asyncio
async def test_step_processor_executes_personality_tool_successfully(
    step_processor_for_personality_tests: StepProcessor,
    mock_personality_pack_manager: MagicMock,
    mock_event_publisher: MagicMock,
    mock_context_manager: MagicMock
):
    """
    Tests that StepProcessor correctly executes a tool via PersonalityPackManager
    when the step_type is TOOL_CALL and it's not a built-in memory tool.
    """
    turn_id = "turn_personality_tool_123"
    step_id = "step_pt_789"
    session_id = "session_pt_abc"
    test_personality_id = "personality_with_tools_v1"
    tool_name = "get_current_time"
    tool_args = {"timezone": "UTC"}
    expected_tool_result = {"time": "2025-05-13T10:00:00Z"}

    # 1. Mock PersonalityConfig (as returned by manager.get_personality)
    mock_personality_config = PersonalityConfig(
        id=test_personality_id,
        name="ToolExecutivePersonality",
        description="A personality that executes tools.",
        system_prompt="I use tools.",
        provider_id="openai", # Default provider for the personality
        llm=LLMConfig(model="gpt-3.5-turbo") # Default LLM for the personality
        # Tools themselves are not part of PersonalityConfig, manager handles execution
    )
    mock_personality_pack_manager.get_personality.return_value = mock_personality_config

    # 2. Mock PersonalityPackManager's execute_tool method
    mock_personality_pack_manager.execute_tool.return_value = expected_tool_result

    # 3. Mock TurnContext (as returned by context_manager.get_turn_context)
    mock_turn_context = MagicMock(spec=TurnContext)
    mock_turn_context.turn_id = turn_id
    mock_turn_context.session_id = session_id
    mock_turn_context.personality_id = test_personality_id
    # Add other fields if StepProcessor directly uses them from turn_context before tool call
    # For TOOL_CALL, primary use is personality_id for the manager.
    mock_context_manager.get_turn_context.return_value = mock_turn_context

    # 4. Create StepEventPayload for a TOOL_CALL
    step_payload = StepEventPayload(
        turn_id=turn_id,
        step_id=step_id,
        step_type="TOOL_CALL",
        step_config={
            "tool_name": tool_name,
            "args": tool_args
        },
        session_id=session_id,
        # invocation_id, parent_id, trace_id can be added if needed
    )

    # 5. Act: Call handle_step_event
    await step_processor_for_personality_tests.handle_step_event(step_payload)

    # 6. Assertions
    # Assert PersonalityPackManager.get_personality was called to load the personality for the turn
    mock_personality_pack_manager.get_personality.assert_called_once_with(test_personality_id)

    # Assert PersonalityPackManager.execute_tool was called correctly
    mock_personality_pack_manager.execute_tool.assert_called_once_with(
        personality_id=test_personality_id,
        tool_name=tool_name,
        tool_args=tool_args
    )

    # Assert a StepResultEvent was published with the tool's output
    assert mock_event_publisher.publish.call_count == 1
    published_event_envelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.event_type == EventType.STEP_RESULT
    
    result_payload: StepResultEventPayload = published_event_envelope.payload
    assert result_payload.turn_id == turn_id
    assert result_payload.step_id == step_id
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == expected_tool_result
    assert result_payload.error_message is None
    # Check metrics if specific metrics are expected for successful tool calls
    assert result_payload.metrics is not None
    assert isinstance(result_payload.metrics.duration_ms, (int, float))
    assert result_payload.metrics.duration_ms > 0

@pytest.mark.asyncio
async def test_step_processor_handles_tool_not_found_from_personality_manager(
    step_processor_for_personality_tests: StepProcessor,
    mock_personality_pack_manager: MagicMock,
    mock_event_publisher: MagicMock,
    mock_context_manager: MagicMock 
):
    """
    Tests that StepProcessor correctly handles ToolNotFoundError when a tool 
    is not found by the PersonalityPackManager.
    """
    turn_id = "turn_tnf_456"
    step_id = "step_tnf_123"
    session_id = "session_tnf_def"
    test_personality_id = "personality_for_tnf_v1"
    tool_name = "non_existent_tool"
    tool_args = {"param": "value"}

    # 1. Mock PersonalityConfig
    mock_personality_config = PersonalityConfig(
        id=test_personality_id,
        name="TNFPersonality",
        description="A personality for testing tool not found.",
        system_prompt="I try to use tools.",
        provider_id="openai",
        llm=LLMConfig(model="gpt-3.5-turbo")
    )
    mock_personality_pack_manager.get_personality.return_value = mock_personality_config

    # 2. Mock PersonalityPackManager.execute_tool to raise ToolNotFoundError
    error_message = f"Tool '{tool_name}' not found in personality '{test_personality_id}'."
    mock_personality_pack_manager.execute_tool.side_effect = ToolNotFoundError(
        tool_name=tool_name, 
        personality_id=test_personality_id
    )

    # 3. Mock TurnContext
    mock_turn_context = MagicMock(spec=TurnContext)
    mock_turn_context.turn_id = turn_id
    mock_turn_context.session_id = session_id
    mock_turn_context.personality_id = test_personality_id
    mock_context_manager.get_turn_context.return_value = mock_turn_context

    # 4. Create StepEventPayload
    step_payload = StepEventPayload(
        turn_id=turn_id,
        step_id=step_id,
        step_type="TOOL_CALL",
        step_config={
            "tool_name": tool_name,
            "args": tool_args
        },
        session_id=session_id,
    )

    # 5. Act: Call handle_step_event
    await step_processor_for_personality_tests.handle_step_event(step_payload)

    # 6. Assertions
    mock_personality_pack_manager.get_personality.assert_called_once_with(test_personality_id)
    mock_personality_pack_manager.execute_tool.assert_called_once_with(
        personality_id=test_personality_id,
        tool_name=tool_name,
        tool_args=tool_args
    )

    assert mock_event_publisher.publish.call_count == 1
    published_event_envelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.event_type == EventType.STEP_RESULT
    
    result_payload: StepResultEventPayload = published_event_envelope.payload
    assert result_payload.turn_id == turn_id
    assert result_payload.step_id == step_id
    assert result_payload.status == "FAILED"
    assert result_payload.output is None
    # The error message in runtime.py is `str(e)` for ToolNotFoundError
    assert result_payload.error_message == error_message 
    assert result_payload.metrics is not None
    assert isinstance(result_payload.metrics.duration_ms, (int, float))
    assert result_payload.metrics.duration_ms > 0

@pytest.mark.asyncio
async def test_step_processor_handles_tool_execution_error_from_personality_manager(
    step_processor_for_personality_tests: StepProcessor,
    mock_personality_pack_manager: MagicMock,
    mock_event_publisher: MagicMock,
    mock_context_manager: MagicMock 
):
    """
    Tests that StepProcessor correctly handles ToolExecutionError when a tool 
    fails during execution by the PersonalityPackManager.
    """
    turn_id = "turn_texe_789"
    step_id = "step_texe_456"
    session_id = "session_texe_ghi"
    test_personality_id = "personality_for_texe_v1"
    tool_name = "failing_tool"
    tool_args = {"input": 123}
    original_exception_message = "Internal tool error: Division by zero."

    # 1. Mock PersonalityConfig
    mock_personality_config = PersonalityConfig(
        id=test_personality_id,
        name="TExePersonality",
        description="A personality for testing tool execution errors.",
        system_prompt="I try to use tools, but sometimes they fail.",
        provider_id="openai",
        llm=LLMConfig(model="gpt-3.5-turbo")
    )
    mock_personality_pack_manager.get_personality.return_value = mock_personality_config

    # 2. Mock PersonalityPackManager.execute_tool to raise ToolExecutionError
    tool_execution_err = ToolExecutionError(
        tool_name=tool_name, 
        personality_id=test_personality_id,
        original_error=ValueError(original_exception_message) # Example original error
    )
    mock_personality_pack_manager.execute_tool.side_effect = tool_execution_err

    # 3. Mock TurnContext
    mock_turn_context = MagicMock(spec=TurnContext)
    mock_turn_context.turn_id = turn_id
    mock_turn_context.session_id = session_id
    mock_turn_context.personality_id = test_personality_id
    mock_context_manager.get_turn_context.return_value = mock_turn_context

    # 4. Create StepEventPayload
    step_payload = StepEventPayload(
        turn_id=turn_id,
        step_id=step_id,
        step_type="TOOL_CALL",
        step_config={
            "tool_name": tool_name,
            "args": tool_args
        },
        session_id=session_id,
    )

    # 5. Act: Call handle_step_event
    await step_processor_for_personality_tests.handle_step_event(step_payload)

    # 6. Assertions
    mock_personality_pack_manager.get_personality.assert_called_once_with(test_personality_id)
    mock_personality_pack_manager.execute_tool.assert_called_once_with(
        personality_id=test_personality_id,
        tool_name=tool_name,
        tool_args=tool_args
    )

    assert mock_event_publisher.publish.call_count == 1
    published_event_envelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.event_type == EventType.STEP_RESULT
    
    result_payload: StepResultEventPayload = published_event_envelope.payload
    assert result_payload.turn_id == turn_id
    assert result_payload.step_id == step_id
    assert result_payload.status == "FAILED"
    assert result_payload.output is None
    # The error_message should be str(tool_execution_err)
    assert result_payload.error_message == str(tool_execution_err) 
    assert result_payload.metrics is not None
    assert isinstance(result_payload.metrics.duration_ms, (int, float))
    assert result_payload.metrics.duration_ms > 0

@pytest.mark.asyncio
async def test_tool_call_for_memory_tool_search_memory_successful(
    step_processor_for_personality_tests: StepProcessor,
    mock_memory_manager: MagicMock, # Specific mock for this test
    mock_personality_pack_manager: MagicMock, # To assert it's NOT called
    mock_event_publisher: MagicMock,
    mock_context_manager: MagicMock 
):
    """
    Tests that StepProcessor correctly handles a TOOL_CALL for a built-in
    memory tool (e.g., search_memory) and does NOT call PersonalityPackManager.
    """
    turn_id = "turn_mem_search_123"
    step_id = "step_ms_789"
    session_id = "session_ms_abc"
    test_personality_id = "personality_for_mem_search_v1"
    tool_name = "search_memory"
    tool_args = {"query": "latest project updates", "top_k": 3}
    expected_search_result = [{"id": "doc1", "text": "Update A"}]

    # 1. Mock PersonalityConfig (though not strictly needed for tool execution path here)
    mock_personality_config = PersonalityConfig(
        id=test_personality_id,
        name="MemorySearchPersonality",
        description="A personality that might use memory.",
        system_prompt="I search memory.",
        provider_id="openai",
        llm=LLMConfig(model="gpt-3.5-turbo")
    )
    mock_personality_pack_manager.get_personality.return_value = mock_personality_config

    # 2. Mock MemoryManager's search method
    mock_memory_manager.search = AsyncMock(return_value=expected_search_result)

    # 3. Mock TurnContext
    mock_turn_context = MagicMock(spec=TurnContext)
    mock_turn_context.turn_id = turn_id
    mock_turn_context.session_id = session_id
    mock_turn_context.personality_id = test_personality_id 
    mock_context_manager.get_turn_context.return_value = mock_turn_context

    # 4. Create StepEventPayload for a TOOL_CALL with a memory tool
    step_payload = StepEventPayload(
        turn_id=turn_id,
        step_id=step_id,
        step_type="TOOL_CALL",
        step_config={
            "tool_name": tool_name,
            "args": tool_args
        },
        session_id=session_id,
    )

    # 5. Act: Call handle_step_event
    await step_processor_for_personality_tests.handle_step_event(step_payload)

    # 6. Assertions
    # Assert MemoryManager.search was called correctly
    mock_memory_manager.search.assert_called_once_with(
        query=tool_args["query"],
        top_k=tool_args["top_k"],
        filters=None # As filters was not in tool_args, it defaults to None in runtime
    )

    # Assert PersonalityPackManager.execute_tool was NOT called
    mock_personality_pack_manager.execute_tool.assert_not_called()

    # Assert a StepResultEvent was published with the search result
    assert mock_event_publisher.publish.call_count == 1
    published_event_envelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.event_type == EventType.STEP_RESULT
    
    result_payload: StepResultEventPayload = published_event_envelope.payload
    assert result_payload.turn_id == turn_id
    assert result_payload.step_id == step_id
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == expected_search_result
    assert result_payload.error_message is None
    assert result_payload.metrics is not None
    assert isinstance(result_payload.metrics.duration_ms, (int, float))
    assert result_payload.metrics.duration_ms > 0

@pytest.mark.asyncio
async def test_tool_call_for_memory_tool_retrieve_from_memory_successful(
    step_processor_for_personality_tests: StepProcessor,
    mock_memory_manager: MagicMock, 
    mock_personality_pack_manager: MagicMock, 
    mock_event_publisher: MagicMock,
    mock_context_manager: MagicMock 
):
    """
    Tests that StepProcessor correctly handles a TOOL_CALL for retrieving
    data from memory and does NOT call PersonalityPackManager.
    """
    turn_id = "turn_mem_retrieve_456"
    step_id = "step_mr_123"
    session_id = "session_mr_def"
    test_personality_id = "personality_for_mem_retrieve_v1"
    tool_name = "retrieve_from_memory"
    doc_id_to_retrieve = "doc_xyz_789"
    tool_args = {"doc_id": doc_id_to_retrieve}
    expected_retrieved_doc = {"id": doc_id_to_retrieve, "text": "This is the content of doc xyz.", "metadata": {"source": "test"}}

    # 1. Mock PersonalityConfig (still needed as StepProcessor tries to load it)
    mock_personality_config = PersonalityConfig(
        id=test_personality_id,
        name="MemoryRetrievePersonality",
        description="A personality that might retrieve from memory.",
        system_prompt="I retrieve from memory.",
        provider_id="openai",
        llm=LLMConfig(model="gpt-3.5-turbo")
    )
    mock_personality_pack_manager.get_personality.return_value = mock_personality_config

    # 2. Mock MemoryManager's read method
    mock_memory_manager.read = AsyncMock(return_value=expected_retrieved_doc)

    # 3. Mock TurnContext
    mock_turn_context = MagicMock(spec=TurnContext)
    mock_turn_context.turn_id = turn_id
    mock_turn_context.session_id = session_id
    mock_turn_context.personality_id = test_personality_id 
    mock_context_manager.get_turn_context.return_value = mock_turn_context

    # 4. Create StepEventPayload for a TOOL_CALL with retrieve_from_memory
    step_payload = StepEventPayload(
        turn_id=turn_id,
        step_id=step_id,
        step_type="TOOL_CALL",
        step_config={
            "tool_name": tool_name,
            "args": tool_args
        },
        session_id=session_id,
    )

    # 5. Act: Call handle_step_event
    await step_processor_for_personality_tests.handle_step_event(step_payload)

    # 6. Assertions
    # Assert MemoryManager.read was called correctly
    mock_memory_manager.read.assert_called_once_with(key=doc_id_to_retrieve)

    # Assert PersonalityPackManager.execute_tool was NOT called
    mock_personality_pack_manager.execute_tool.assert_not_called()

    # Assert a StepResultEvent was published with the retrieved document
    assert mock_event_publisher.publish.call_count == 1
    published_event_envelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.event_type == EventType.STEP_RESULT
    
    result_payload: StepResultEventPayload = published_event_envelope.payload
    assert result_payload.turn_id == turn_id
    assert result_payload.step_id == step_id
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == expected_retrieved_doc
    assert result_payload.error_message is None
    assert result_payload.metrics is not None
    assert isinstance(result_payload.metrics.duration_ms, (int, float))
    assert result_payload.metrics.duration_ms > 0

@pytest.mark.asyncio
async def test_tool_call_for_memory_tool_add_to_memory_successful(
    step_processor_for_personality_tests: StepProcessor,
    mock_memory_manager: MagicMock, 
    mock_personality_pack_manager: MagicMock, 
    mock_event_publisher: MagicMock,
    mock_context_manager: MagicMock 
):
    """
    Tests that StepProcessor correctly handles a TOOL_CALL for adding data
    to memory and does NOT call PersonalityPackManager.
    """
    turn_id = "turn_mem_add_789"
    step_id = "step_ma_456"
    session_id = "session_ma_ghi"
    test_personality_id = "personality_for_mem_add_v1"
    tool_name = "add_to_memory"
    doc_to_add = {
        "doc_id": "new_doc_123",
        "text": "This is a new document to be added.",
        "metadata": {"source": "test_add", "category": "integration"}
    }
    tool_args = doc_to_add # Arguments for add_to_memory tool
    expected_output = {"status": "write successful", "doc_id": doc_to_add["doc_id"]}

    # 1. Mock PersonalityConfig
    mock_personality_config = PersonalityConfig(
        id=test_personality_id,
        name="MemoryAddPersonality",
        description="A personality that might add to memory.",
        system_prompt="I add to memory.",
        provider_id="openai",
        llm=LLMConfig(model="gpt-3.5-turbo")
    )
    mock_personality_pack_manager.get_personality.return_value = mock_personality_config

    # 2. Mock MemoryManager's write method
    mock_memory_manager.write = AsyncMock(return_value=None) # write usually doesn't return significant data

    # 3. Mock TurnContext
    mock_turn_context = MagicMock(spec=TurnContext)
    mock_turn_context.turn_id = turn_id
    mock_turn_context.session_id = session_id
    mock_turn_context.personality_id = test_personality_id 
    mock_context_manager.get_turn_context.return_value = mock_turn_context

    # 4. Create StepEventPayload for a TOOL_CALL with add_to_memory
    step_payload = StepEventPayload(
        turn_id=turn_id,
        step_id=step_id,
        step_type="TOOL_CALL",
        step_config={
            "tool_name": tool_name,
            "args": tool_args
        },
        session_id=session_id,
    )

    # 5. Act: Call handle_step_event
    await step_processor_for_personality_tests.handle_step_event(step_payload)

    # 6. Assertions
    # Assert MemoryManager.write was called correctly
    mock_memory_manager.write.assert_called_once_with(
        key=doc_to_add["doc_id"],
        data={"text": doc_to_add["text"], "metadata": doc_to_add["metadata"]}
    )

    # Assert PersonalityPackManager.execute_tool was NOT called
    mock_personality_pack_manager.execute_tool.assert_not_called()

    # Assert a StepResultEvent was published
    assert mock_event_publisher.publish.call_count == 1
    published_event_envelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.event_type == EventType.STEP_RESULT
    
    result_payload: StepResultEventPayload = published_event_envelope.payload
    assert result_payload.turn_id == turn_id
    assert result_payload.step_id == step_id
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == expected_output
    assert result_payload.error_message is None
    assert result_payload.metrics is not None
    assert isinstance(result_payload.metrics.duration_ms, (int, float))
    assert result_payload.metrics.duration_ms > 0

@pytest.mark.asyncio
async def test_tool_call_for_memory_tool_delete_from_memory_successful(
    step_processor_for_personality_tests: StepProcessor,
    mock_memory_manager: MagicMock, 
    mock_personality_pack_manager: MagicMock, 
    mock_event_publisher: MagicMock,
    mock_context_manager: MagicMock 
):
    """
    Tests that StepProcessor correctly handles a TOOL_CALL for deleting data
    from memory and does NOT call PersonalityPackManager.
    """
    turn_id = "turn_mem_delete_101"
    step_id = "step_md_789"
    session_id = "session_md_jkl"
    test_personality_id = "personality_for_mem_delete_v1"
    tool_name = "delete_from_memory"
    doc_id_to_delete = "doc_to_remove_456"
    tool_args = {"doc_id": doc_id_to_delete}
    expected_output = {"status": "delete successful", "doc_id": doc_id_to_delete}

    # 1. Mock PersonalityConfig
    mock_personality_config = PersonalityConfig(
        id=test_personality_id,
        name="MemoryDeletePersonality",
        description="A personality that might delete from memory.",
        system_prompt="I delete from memory.",
        provider_id="openai",
        llm=LLMConfig(model="gpt-3.5-turbo")
    )
    mock_personality_pack_manager.get_personality.return_value = mock_personality_config

    # 2. Mock MemoryManager's delete method
    mock_memory_manager.delete = AsyncMock(return_value=None) # delete usually doesn't return significant data

    # 3. Mock TurnContext
    mock_turn_context = MagicMock(spec=TurnContext)
    mock_turn_context.turn_id = turn_id
    mock_turn_context.session_id = session_id
    mock_turn_context.personality_id = test_personality_id 
    mock_context_manager.get_turn_context.return_value = mock_turn_context

    # 4. Create StepEventPayload for a TOOL_CALL with delete_from_memory
    step_payload = StepEventPayload(
        turn_id=turn_id,
        step_id=step_id,
        step_type="TOOL_CALL",
        step_config={
            "tool_name": tool_name,
            "args": tool_args
        },
        session_id=session_id,
    )

    # 5. Act: Call handle_step_event
    await step_processor_for_personality_tests.handle_step_event(step_payload)

    # 6. Assertions
    # Assert MemoryManager.delete was called correctly
    mock_memory_manager.delete.assert_called_once_with(key=doc_id_to_delete)

    # Assert PersonalityPackManager.execute_tool was NOT called
    mock_personality_pack_manager.execute_tool.assert_not_called()

    # Assert a StepResultEvent was published
    assert mock_event_publisher.publish.call_count == 1
    published_event_envelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.event_type == EventType.STEP_RESULT
    
    result_payload: StepResultEventPayload = published_event_envelope.payload
    assert result_payload.turn_id == turn_id
    assert result_payload.step_id == step_id
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == expected_output
    assert result_payload.error_message is None
    assert result_payload.metrics is not None
    assert isinstance(result_payload.metrics.duration_ms, (int, float))
    assert result_payload.metrics.duration_ms > 0

# ... (rest of the file, including other test placeholders) 