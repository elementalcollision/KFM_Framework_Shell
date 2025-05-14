from unittest.mock import AsyncMock, MagicMock
import pytest
from core.config import AppConfig
from core.events import EventEnvelope, StepEventPayload
from core.personality import PersonalityManager
from core.step_processor import StepProcessor
from core.types import Message

@pytest.mark.asyncio
async def test_step_processor_uses_openai_provider_for_generation(
    step_processor_fixture: StepProcessor, 
    mock_provider_factory: MagicMock, 
    mock_openai_provider: MagicMock, 
    mock_event_publisher: MagicMock,
    mock_personality_manager: MagicMock, # To get personality for provider and model
    app_config_fixture: AppConfig # To resolve provider_id if not in personality
):
    """
    Tests that the StepProcessor correctly uses the OpenAI provider
    when handling an llm_generate step configured for OpenAI.
    """
    # Arrange
    step_processor = step_processor_fixture
    test_turn_id = "turn_test_openai_generate"
    test_plan_id = "plan_test_openai_generate"
    test_step_id = "step_test_openai_generate"
    test_session_id = "session_test_openai_generate"
    test_trace_id = "trace_test_openai_generate"
    user_query = "Hello OpenAI!"

    # Get the default test personality from the mock manager
    test_personality = mock_personality_manager.get_personality("test_default_personality")
    # Ensure this personality uses openai_chat as configured in its fixture
    assert test_personality.provider_id == "openai_chat"
    
    # Mock the get_personality call on the instance of personality_manager used by StepProcessor
    # (though the fixture already sets a default return value, explicit is safer for clarity)
    # We need to ensure that the specific instance of mock_personality_manager used by
    # step_processor_fixture.personality_manager is the one we are configuring here if they are different.
    # However, pytest fixtures inject the same mock instance if typed correctly.
    step_processor.personality_manager.get_personality.return_value = test_personality

    # Create a StepEventPayload for an llm_generate step
    # The StepProcessor will use the personality_id from the payload to fetch the personality,
    # then use personality.provider_id to get the provider.
    payload = StepEventPayload(
        turn_id=test_turn_id,
        plan_id=test_plan_id,
        step_id=test_step_id,
        step_type="llm_generate",
        session_id=test_session_id,
        trace_id=test_trace_id,
        personality_id=test_personality.id, # Use the ID of the test personality
        inputs={"prompt": user_query}, # Standardized input for llm_generate
        # provider_id and model_name can be overridden in step_config if needed,
        # otherwise, they come from personality.
        # step_config={"provider_id": "openai_chat", "model_name": "gpt-3.5-turbo"} 
    )

    # Expected response from the mocked OpenAI provider
    expected_response_message = Message(role="assistant", content="Mocked OpenAI response for test")
    # We need to configure the mock_openai_provider that is injected into mock_provider_factory
    # The mock_openai_provider fixture already sets a default AsyncMock for generate.
    # We re-assign it here to ensure this specific test's expectation is set.
    mock_openai_provider.generate = AsyncMock(return_value=expected_response_message)

    # Act
    await step_processor.handle_step_event(payload)

    # Assert
    # 1. ProviderFactory.get_provider was called correctly to get the OpenAI provider
    mock_provider_factory.get_provider.assert_called_once_with(
        provider_id=test_personality.provider_id, # Should be "openai_chat"
        app_config=app_config_fixture,
        personality_config=test_personality
    )

    # 2. Mocked OpenAIProvider.generate was called with correct arguments
    expected_messages_to_provider = [
        Message(role="system", content=test_personality.system_prompt),
        Message(role="user", content=user_query)
    ]
    
    # Check how StepProcessor actually calls the provider's generate method.
    # It might pass model_parameters as kwargs or merge them into a dict.
    # For now, assuming a simplified call based on typical provider interfaces.
    # The actual signature of OpenAIProvider.generate and how StepProcessor prepares
    # parameters (especially model_parameters and stream) needs to be known.
    # If model_parameters from personality are automatically included, the assertion needs to reflect that.
    
    # Let's assume the provider's generate method is defined as:
    # async def generate(self, messages: List[Message], model_name: str, stream: bool = False, **kwargs)
    # And StepProcessor passes personality.model_parameters as **kwargs.

    mock_openai_provider.generate.assert_called_once_with(
        messages=expected_messages_to_provider,
        model_name=test_personality.llm.model, # From personality's LLMConfig
        stream=False, # Assuming default for this test, or StepProcessor sets it.
        **test_personality.model_parameters # Pass model parameters from personality
    )

    # 3. EventPublisher.publish was called with a success StepResultEvent
    mock_event_publisher.publish.assert_called_once()
    published_event_envelope: EventEnvelope = mock_event_publisher.publish.call_args[0][0]
    
    assert isinstance(published_event_envelope, EventEnvelope)
    assert published_event_envelope.type == "StepResultEvent"
    assert published_event_envelope.trace_id == test_trace_id
    assert published_event_envelope.session_id == test_session_id
    
    # Assuming StepResultEventPayload is the actual type for the payload
    # from core.events import StepResultEventPayload (needs to be imported if not already)
    # Let's assume it's already imported or we use a more generic check for now.
    
    # The payload of EventEnvelope is defined as: payload: BaseModel | Dict[str, Any]
    # The StepProcessor likely creates a StepResultEventPayload instance.
    # Let's import StepResultEventPayload to be specific.
    from core.events import StepResultEventPayload

    result_payload = published_event_envelope.payload
    assert isinstance(result_payload, StepResultEventPayload)
    assert result_payload.turn_id == test_turn_id
    assert result_payload.plan_id == test_plan_id
    assert result_payload.step_id == test_step_id
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == expected_response_message.model_dump() # Check if output is the message dict
    assert result_payload.error is None
    # TODO: Assert metrics if StepProcessor populates them (e.g., latency)

@pytest.mark.asyncio
async def test_step_processor_llm_generate_with_step_config_overrides(
    step_processor_fixture: StepProcessor,
    mock_provider_factory: MagicMock, 
    mock_openai_provider: MagicMock, # Base personality might use this
    mock_groq_provider: MagicMock,   # Override to this one
    mock_event_publisher: MagicMock,
    mock_personality_manager: MagicMock,
    app_config_fixture: AppConfig 
):
    """
    Tests llm_generate with step_config overriding provider, model, and parameters.
    """
    # Arrange
    step_processor = step_processor_fixture
    user_query = "Hello with overrides!"

    # Base personality (e.g., default OpenAI)
    base_personality = mock_personality_manager.get_personality("test_default_personality")
    assert base_personality.provider_id == "openai_chat"
    step_processor.personality_manager.get_personality.return_value = base_personality

    override_provider_id = "groq_chat"
    override_model_name = "groq-model-override-test"
    override_temperature = 0.99
    override_max_tokens = 123

    # Ensure the override provider (Groq) and its LLM config exist in AppConfig
    assert override_provider_id in app_config_fixture.providers
    assert app_config_fixture.providers[override_provider_id].llm is not None

    payload = StepEventPayload(
        turn_id="turn_gen_override",
        plan_id="plan_gen_override",
        step_id="step_gen_override",
        step_type="llm_generate",
        personality_id=base_personality.id,
        inputs={"prompt": user_query},
        step_config={
            "provider_id": override_provider_id,
            "model_name": override_model_name,
            "temperature": override_temperature,
            "max_tokens": override_max_tokens
            # "stream" could also be overridden here
        }
    )

    expected_response_message = Message(role="assistant", content="Mocked Groq response with overrides")
    mock_groq_provider.generate = AsyncMock(return_value=expected_response_message)
    # Ensure the original provider (OpenAI) is not called if override is effective
    mock_openai_provider.generate = AsyncMock(side_effect=AssertionError("OpenAI provider should not be called"))

    # Act
    await step_processor.handle_step_event(payload)

    # Assert
    # 1. ProviderFactory was called for the OVERRIDDEN provider (Groq)
    mock_provider_factory.get_provider.assert_called_once_with(
        provider_id=override_provider_id,
        app_config=app_config_fixture,
        personality_config=base_personality # Personality is still passed for context, even if provider_id is overridden
    )

    # 2. GroqProvider.generate was called with overridden model and parameters
    expected_messages_to_provider = [
        Message(role="system", content=base_personality.system_prompt),
        Message(role="user", content=user_query)
    ]
    # Parameters should be a merge: AppConfig < Personality < StepConfig
    # For this test, step_config parameters are dominant for specified keys.
    # Other non-specified params would come from AppConfig for Groq or personality if it had groq specific llm params.
    expected_call_params = app_config_fixture.providers[override_provider_id].llm.parameters.copy()
    expected_call_params.update({"temperature": override_temperature, "max_tokens": override_max_tokens}) # Overrides

    mock_groq_provider.generate.assert_called_once_with(
        messages=expected_messages_to_provider,
        model_name=override_model_name,
        stream=False, # Default, as not overridden in step_config for this test
        **expected_call_params
    )
    mock_openai_provider.generate.assert_not_called() # Verify base provider wasn't called

    # 3. Successful event published
    mock_event_publisher.publish.assert_called_once()
    published_event_envelope: EventEnvelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.type == "StepResultEvent"
    result_payload = published_event_envelope.payload
    assert isinstance(result_payload, StepResultEventPayload)
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == expected_response_message.model_dump()

@pytest.mark.asyncio
async def test_step_processor_llm_embed_with_step_config_overrides(
    step_processor_fixture: StepProcessor,
    mock_provider_factory: MagicMock, 
    mock_openai_provider: MagicMock, # Using OpenAI for this test
    mock_event_publisher: MagicMock,
    mock_personality_manager: MagicMock,
    app_config_fixture: AppConfig 
):
    """
    Tests llm_embed with step_config overriding embedding model and parameters.
    """
    # Arrange
    step_processor = step_processor_fixture
    texts_to_embed = ["Text to embed with overrides!"]

    # Base personality (e.g., default OpenAI)
    base_personality = mock_personality_manager.get_personality("test_default_personality")
    assert base_personality.provider_id == "openai_chat"
    step_processor.personality_manager.get_personality.return_value = base_personality

    # Ensure AppConfig has a default embedding model for openai_chat
    default_appconfig_embedding_model = app_config_fixture.providers["openai_chat"].embedding.model
    assert default_appconfig_embedding_model is not None

    override_embedding_model_name = "openai-embed-override-test"
    # Example of an embedding-specific parameter we might override
    override_embedding_params = {"dimensions": 256} 

    payload = StepEventPayload(
        turn_id="turn_embed_override",
        plan_id="plan_embed_override",
        step_id="step_embed_override",
        step_type="llm_embed",
        personality_id=base_personality.id,
        inputs={"texts_to_embed": texts_to_embed},
        step_config={
            # provider_id could be overridden too, but for this test, we focus on model and params
            # "provider_id": "another_embedding_provider", 
            "embedding_model_name": override_embedding_model_name,
            "embedding_parameters": override_embedding_params
        }
    )

    expected_embedding_vectors = [[0.01, 0.02, 0.03]]
    mock_openai_provider.embed = AsyncMock(return_value=expected_embedding_vectors)

    # Act
    await step_processor.handle_step_event(payload)

    # Assert
    # 1. ProviderFactory was called for the correct provider (OpenAI in this case)
    mock_provider_factory.get_provider.assert_called_once_with(
        provider_id=base_personality.provider_id, # openai_chat
        app_config=app_config_fixture,
        personality_config=base_personality
    )

    # 2. OpenAIProvider.embed was called with overridden model and parameters
    # Base parameters from AppConfig for this provider's embedding config
    expected_call_params = app_config_fixture.providers[base_personality.provider_id].embedding.parameters.copy()
    # Update with step_config overrides
    expected_call_params.update(override_embedding_params) 

    mock_openai_provider.embed.assert_called_once_with(
        texts=texts_to_embed,
        model_name=override_embedding_model_name,
        **expected_call_params
    )

    # 3. Successful event published
    mock_event_publisher.publish.assert_called_once()
    published_event_envelope: EventEnvelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.type == "StepResultEvent"
    result_payload = published_event_envelope.payload
    assert isinstance(result_payload, StepResultEventPayload)
    assert result_payload.status == "SUCCEEDED"
    assert result_payload.output == {"embeddings": expected_embedding_vectors}
    assert result_payload.error is None # THIS IS THE LINE TO ENSURE IS PRESENT

@pytest.mark.asyncio
async def test_step_processor_handles_provider_error_on_generate(
    step_processor_fixture: StepProcessor,
    mock_provider_factory: MagicMock,
    mock_openai_provider: MagicMock,
    mock_event_publisher: MagicMock,
    mock_personality_manager: MagicMock,
    app_config_fixture: AppConfig
):
    """
    Tests handling of a provider error on generate.
    """
    # Arrange
    step_processor = step_processor_fixture
    user_query = "Hello with error!"

    # Base personality (e.g., default OpenAI)
    base_personality = mock_personality_manager.get_personality("test_default_personality")
    assert base_personality.provider_id == "openai_chat"
    step_processor.personality_manager.get_personality.return_value = base_personality

    # Mock the provider to raise an exception
    mock_openai_provider.generate = AsyncMock(side_effect=Exception("Provider error"))

    # Create a StepEventPayload for an llm_generate step
    payload = StepEventPayload(
        turn_id="turn_error",
        plan_id="plan_error",
        step_id="step_error",
        step_type="llm_generate",
        personality_id=base_personality.id,
        inputs={"prompt": user_query},
        step_config={
            "provider_id": base_personality.provider_id,
            "model_name": base_personality.llm.model,
            "temperature": base_personality.llm.parameters.temperature,
            "max_tokens": base_personality.llm.parameters.max_tokens
        }
    )

    # Act
    await step_processor.handle_step_event(payload)

    # Assert
    # 1. ProviderFactory was called for the correct provider (OpenAI in this case)
    mock_provider_factory.get_provider.assert_called_once_with(
        provider_id=base_personality.provider_id, # openai_chat
        app_config=app_config_fixture,
        personality_config=base_personality
    )

    # 2. Mocked OpenAIProvider.generate was called with correct arguments
    expected_messages_to_provider = [
        Message(role="system", content=base_personality.system_prompt),
        Message(role="user", content=user_query)
    ]
    
    mock_openai_provider.generate.assert_called_once_with(
        messages=expected_messages_to_provider,
        model_name=base_personality.llm.model, # From personality's LLMConfig
        stream=False, # Assuming default for this test, or StepProcessor sets it.
        **base_personality.model_parameters # Pass model parameters from personality
    )

    # 3. EventPublisher.publish was called with a failed StepResultEvent
    mock_event_publisher.publish.assert_called_once()
    published_event_envelope: EventEnvelope = mock_event_publisher.publish.call_args[0][0]
    
    assert isinstance(published_event_envelope, EventEnvelope)
    assert published_event_envelope.type == "StepResultEvent"
    result_payload = published_event_envelope.payload
    assert isinstance(result_payload, StepResultEventPayload)
    assert result_payload.status == "FAILED"
    assert result_payload.output is None
    assert result_payload.error is not None
    # The StepProcessor should populate the error field of StepResultEventPayload
    # based on the ProviderError. The exact structure depends on StepProcessor's implementation.
    # Let's assume it at least includes the message and type.
    error_message = "Provider error"
    error_type = "ProviderError" # StepProcessor might generalize or keep specific type
    original_exception_details = "Provider error"
    assert result_payload.error.get("message") == error_message
    assert result_payload.error.get("type") == error_type
    assert result_payload.error.get("provider_name") == "openai_chat"
    assert result_payload.error.get("original_error_type") == error_type
    assert result_payload.error.get("details") == original_exception_details

@pytest.mark.asyncio
async def test_step_processor_handles_unsupported_embedding_provider_config(
    step_processor_fixture: StepProcessor,
    mock_provider_factory: MagicMock, 
    mock_openai_provider: MagicMock, # Using OpenAI for this test
    mock_event_publisher: MagicMock,
    mock_personality_manager: MagicMock,
    app_config_fixture: AppConfig 
):
    """
    Tests handling of an unsupported embedding provider configuration.
    """
    # Arrange
    step_processor = step_processor_fixture
    texts_to_embed = ["Text to embed with unsupported configuration!"]

    # Base personality (e.g., default OpenAI)
    base_personality = mock_personality_manager.get_personality("test_default_personality")
    assert base_personality.provider_id == "openai_chat"
    step_processor.personality_manager.get_personality.return_value = base_personality

    # Ensure AppConfig has a default embedding model for openai_chat
    default_appconfig_embedding_model = app_config_fixture.providers["openai_chat"].embedding.model
    assert default_appconfig_embedding_model is not None

    override_embedding_model_name = "unsupported-embedding-model-test"
    # Example of an embedding-specific parameter we might override
    override_embedding_params = {"dimensions": 256} 

    payload = StepEventPayload(
        turn_id="turn_embed_unsupported",
        plan_id="plan_embed_unsupported",
        step_id="step_embed_unsupported",
        step_type="llm_embed",
        personality_id=base_personality.id,
        inputs={"texts_to_embed": texts_to_embed},
        step_config={
            # provider_id could be overridden too, but for this test, we focus on model and params
            # "provider_id": "another_embedding_provider", 
            "embedding_model_name": override_embedding_model_name,
            "embedding_parameters": override_embedding_params
        }
    )

    # Act
    await step_processor.handle_step_event(payload)

    # Assert
    # 1. ProviderFactory was called for the correct provider (OpenAI in this case)
    mock_provider_factory.get_provider.assert_called_once_with(
        provider_id=base_personality.provider_id, # openai_chat
        app_config=app_config_fixture,
        personality_config=base_personality
    )

    # 2. OpenAIProvider.embed was called with overridden model and parameters
    # Base parameters from AppConfig for this provider's embedding config
    expected_call_params = app_config_fixture.providers[base_personality.provider_id].embedding.parameters.copy()
    # Update with step_config overrides
    expected_call_params.update(override_embedding_params) 

    mock_openai_provider.embed.assert_called_once_with(
        texts=texts_to_embed,
        model_name=override_embedding_model_name,
        **expected_call_params
    )

    # 3. Successful event published
    mock_event_publisher.publish.assert_called_once()
    published_event_envelope: EventEnvelope = mock_event_publisher.publish.call_args[0][0]
    assert published_event_envelope.type == "StepResultEvent"
    result_payload = published_event_envelope.payload
    assert isinstance(result_payload, StepResultEventPayload)
    assert result_payload.status == "FAILED"
    assert result_payload.output is None
    assert result_payload.error is not None
    # The StepProcessor should populate the error field of StepResultEventPayload
    # based on the ProviderError. The exact structure depends on StepProcessor's implementation.
    # Let's assume it at least includes the message and type.
    error_message = "Unsupported embedding provider configuration"
    error_type = "ProviderError" # StepProcessor might generalize or keep specific type
    original_exception_details = "Unsupported embedding provider configuration"
    assert result_payload.error.get("message") == error_message
    assert result_payload.error.get("type") == error_type
    assert result_payload.error.get("provider_name") == "openai_chat"
    assert result_payload.error.get("original_error_type") == error_type
    assert result_payload.error.get("details") == original_exception_details