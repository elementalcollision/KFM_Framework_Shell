# Tests for RedisCacheService 

import pytest
import pytest_asyncio
import json
from unittest.mock import AsyncMock, patch
import asyncio
import redis.exceptions
from redis.exceptions import RedisError

from core.config import RedisConfig, AppConfig, CoreRuntimeConfig, ModelPricing, OpenAIProviderConfig, AnthropicProviderConfig, GroqProviderConfig, MemoryConfig, LanceDBConfig, ProvidersConfig, IggyIntegrationConfig, PersonalitiesConfig # Assuming these are needed for AppConfig
from memory.redis_cache import RedisCacheService

# Minimal AppConfig for RedisCacheService initialization
@pytest.fixture
def app_config():
    # Create minimal nested configs. Replace with actual default values or mocks if needed.
    core_runtime_cfg = CoreRuntimeConfig(default_provider_id="test_provider", default_personality_id="test_pers", turn_processing_timeout_seconds=60)
    memory_cfg = MemoryConfig(
        cache_ttl_seconds=300, 
        lancedb_config=LanceDBConfig(uri="/tmp/lancedb", table_name="vectors"), # Dummy LanceDB
        # Initialize RedisConfig using the url field
        redis=RedisConfig(url="redis://localhost:6379/0") # Pass RedisConfig to AppConfig via memory field?
    )
    
    return AppConfig(
        core_runtime=core_runtime_cfg,
        log_level="INFO",
        # Need to pass provider configs under the 'providers' field now
        providers=ProvidersConfig(
             openai=OpenAIProviderConfig(), 
             anthropic=AnthropicProviderConfig(), 
             groq=GroqProviderConfig()
        ),
        memory=memory_cfg, # Pass the MemoryConfig containing RedisConfig
        iggy_integration=IggyIntegrationConfig(), # Add dummy Iggy config
        personalities=PersonalitiesConfig(directory="./tests/fake_personalities"), # Add dummy personalities config
        # redis field in AppConfig is separate, can initialize if needed for other tests
        redis=RedisConfig(url="redis://localhost:6379/1") # Example separate redis if needed
    )

@pytest_asyncio.fixture
async def mock_redis_client():
    """Creates a mock Redis client."""
    # Create an AsyncMock of Redis.from_url
    client = AsyncMock(spec=redis.asyncio.Redis)
    
    # For methods that need to be awaited and work in tests
    async def mock_set(*args, **kwargs):
        # Record that this was called with args & kwargs
        return True  # Success response
    
    async def mock_delete(*args, **kwargs):
        # Record that this was called with args & kwargs
        return 1  # Number of keys deleted
        
    # Set up the methods we'll use in tests
    client.set = AsyncMock(side_effect=mock_set)
    client.get = AsyncMock()
    client.delete = AsyncMock(side_effect=mock_delete)
    client.close = AsyncMock()
    
    return client

@pytest_asyncio.fixture
async def redis_cache_service(mock_redis_client):
    """Test fixture that uses a mocked Redis client."""
    # Patch the Redis.from_url constructor to return our mock
    with patch('redis.asyncio.Redis.from_url', return_value=mock_redis_client):
        # Create the Redis service with real initialization
        service = RedisCacheService("redis://localhost:6379/1", default_ttl=3600)
        # Make sure the mock is used
        assert service.redis_client is mock_redis_client
        yield service
        # No explicit close needed here - it's handled by the test

@pytest.mark.asyncio
async def test_write_success(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock, app_config: AppConfig):
    key = "test_key"
    value = {"data": "some_value"}
    
    await redis_cache_service.write(key, value)
    
    # Check that client.set was called with the correct key and serialized value
    # We don't check ex parameter since we're using side_effect for actual awaiting
    mock_redis_client.set.assert_awaited_once()
    # Verify the args were correct
    args, kwargs = mock_redis_client.set.call_args
    assert args[0] == key
    assert args[1] == json.dumps(value)
    assert "ex" in kwargs  # TTL should be in kwargs

@pytest.mark.asyncio
async def test_write_with_custom_ttl(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock):
    key = "temp_key"
    value = {"test": "temporary_value"}  # Use a dict to match what the code expects to JSON serialize
    custom_ttl = 120  # 2 minutes
    
    await redis_cache_service.write(key, value, ttl=custom_ttl)
    
    # Verify set was called with the right args
    mock_redis_client.set.assert_awaited_once()
    args, kwargs = mock_redis_client.set.call_args
    assert args[0] == key
    assert args[1] == json.dumps(value)
    assert kwargs.get("ex") == custom_ttl  # Custom TTL should be used

@pytest.mark.asyncio
async def test_read_success_hit(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock):
    key = "test_key_hit"
    expected_value = {"data": "value_in_cache"}
    # Configure the mock_redis_client.get to return a serialized version of expected_value
    mock_redis_client.get.return_value = json.dumps(expected_value).encode('utf-8')

    actual_value = await redis_cache_service.read(key)

    mock_redis_client.get.assert_awaited_once_with(key)
    assert actual_value == expected_value

@pytest.mark.asyncio
async def test_read_success_miss(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock):
    key = "test_key_miss"
    # Configure the mock_redis_client.get to return None (simulating key not found)
    mock_redis_client.get.return_value = None

    actual_value = await redis_cache_service.read(key)

    mock_redis_client.get.assert_awaited_once_with(key)
    assert actual_value is None

@pytest.mark.asyncio
async def test_serialization_deserialization(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock):
    key = "complex_obj_key"
    complex_value = {"name": "Test", "version": 1.0, "items": [1, 2, {"sub_item": "data"}]}
    
    # Our write implementation now passes ttl as ex param
    await redis_cache_service.write(key, complex_value)
    mock_redis_client.set.assert_awaited_once()
    
    # Verify the args were correct
    args, kwargs = mock_redis_client.set.call_args
    assert args[0] == key
    assert args[1] == json.dumps(complex_value)
    assert "ex" in kwargs  # TTL should be in kwargs
    
    # Configure mock_redis_client.get to return the JSON string
    async def mock_get(key):
        # Return JSON string to simulate the stored value
        return json.dumps(complex_value)
        
    mock_redis_client.get.side_effect = mock_get
    
    # Test reading back
    value = await redis_cache_service.read(key)
    mock_redis_client.get.assert_awaited_once_with(key)
    
    # Value should be deserialized to match the original
    assert value == complex_value

@pytest.mark.asyncio
async def test_delete_success(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock):
    key = "test_key_delete"

    await redis_cache_service.delete(key)

    # Check that client.delete was called with the correct key
    mock_redis_client.delete.assert_awaited_once_with(key)

@pytest.mark.asyncio
async def test_read_failure(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock, caplog):
    key = "test_key_read_fail"
    # Configure the mock_redis_client.get to raise an error
    mock_redis_client.get.side_effect = RedisError("Simulated connection error")
    
    # Use caplog fixture to capture logs
    import logging
    caplog.set_level(logging.ERROR)
    
    actual_value = await redis_cache_service.read(key)
    
    # Verify the error was handled and logged appropriately
    assert actual_value is None
    assert "Redis error" in caplog.text
    assert "test_key_read_fail" in caplog.text
    mock_redis_client.get.assert_awaited_once_with(key)

@pytest.mark.asyncio
async def test_delete_failure(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock, caplog):
    key = "test_key_delete_fail"
    # Configure the mock_redis_client.delete to raise an error
    mock_redis_client.delete.side_effect = RedisError("Simulated timeout error")
    
    # Use caplog fixture to capture logs
    import logging
    caplog.set_level(logging.ERROR)
    
    await redis_cache_service.delete(key)
    
    # Verify the error was logged
    assert "Redis error" in caplog.text
    assert "test_key_delete_fail" in caplog.text
    mock_redis_client.delete.assert_awaited_once_with(key)

@pytest.mark.asyncio
async def test_close_closes_connection(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock):
    # Configure mock to ensure close is actually awaited
    async def mock_close():
        return None
    
    mock_redis_client.close = AsyncMock(side_effect=mock_close)
    
    await redis_cache_service.close()
    mock_redis_client.close.assert_awaited_once()  # Redis.close() is the correct method

@pytest.mark.asyncio
async def test_error_handling(redis_cache_service: RedisCacheService, mock_redis_client: AsyncMock, caplog):
    import logging
    key = "error_key_delete"
    # Configure the mock_redis_client.delete to raise an error
    mock_redis_client.delete.side_effect = RedisError("Simulated timeout error")
    
    # Use caplog fixture to capture logs
    caplog.set_level(logging.ERROR)
    
    await redis_cache_service.delete(key)
    
    # Verify error handling
    assert "Redis error" in caplog.text
    assert "Simulated timeout error" in caplog.text
    mock_redis_client.delete.assert_awaited_once_with(key) 