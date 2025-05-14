# Tests for LanceDBVectorStore 

import pytest
import pytest_asyncio
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
import json
from pydantic import Field
from lancedb.pydantic import LanceModel
import asyncio

# Update imports based on AppConfig structure
from core.config import ( 
    LanceDBConfig, AppConfig, CoreRuntimeConfig, 
    ModelPricing, OpenAIProviderConfig, 
    AnthropicProviderConfig, GroqProviderConfig, MemoryConfig, RedisConfig,
    ProvidersConfig, IggyIntegrationConfig, PersonalitiesConfig # Add missing imports
)
from memory.lancedb_store import LanceDBVectorStore

# Minimal AppConfig focused on LanceDBVectorStore
@pytest.fixture
def app_config():
    core_runtime_cfg = CoreRuntimeConfig(default_provider_id="test", default_personality_id="test", turn_processing_timeout_seconds=60)
    # Initialize RedisConfig using url field
    redis_cfg = RedisConfig(url="redis://localhost:6379/0") # Dummy Redis
    lancedb_cfg = LanceDBConfig(uri="/tmp/test_lancedb", table_name="test_vectors")
    # Pass RedisConfig to AppConfig via memory field or direct field?
    # AppConfig has both memory.redis and a top-level redis. Let's assume top-level for now.
    memory_cfg = MemoryConfig(cache_ttl_seconds=300, lancedb=lancedb_cfg)
    
    return AppConfig(
        core_runtime=core_runtime_cfg, 
        log_level="INFO", 
        memory=memory_cfg,
        # Add dummy provider configs under 'providers'
        providers=ProvidersConfig(
            openai=OpenAIProviderConfig(),
            anthropic=AnthropicProviderConfig(),
            groq=GroqProviderConfig()
        ),
        # Add other required dummy configs
        iggy_integration=IggyIntegrationConfig(),
        personalities=PersonalitiesConfig(directory="./tests/fake_personalities"),
        # Pass the initialized redis config to the top-level field
        redis=redis_cfg
    )

@pytest_asyncio.fixture
async def mock_lancedb_table():
    table_mock = AsyncMock(name="LanceTable_MainMock") # Main mock for the table object, methods are async by default if not specified

    # Mock direct methods on the table that are awaited
    table_mock.add = AsyncMock(name="TableAdd_AsyncMock")
    table_mock.delete = AsyncMock(name="TableDelete_AsyncMock")
    table_mock.schema = MagicMock() # schema is an attribute
    table_mock.schema.names = ['id', 'vector', 'text', 'metadata']

    # Mock the fluent search interface: table.search().where().limit().to_pandas_async()
    # table.search() is SYNC and returns a query builder object.
    search_query_builder_mock = MagicMock(name="SearchQueryBuilder_Mock")
    table_mock.search = MagicMock(return_value=search_query_builder_mock, name="TableSearch_SyncMock")

    # Configure the chain on search_query_builder_mock
    # .where() is SYNC and returns the same builder mock for chaining
    search_query_builder_mock.where = MagicMock(return_value=search_query_builder_mock, name="QueryBuilderWhere_SyncMock")
    # .limit() is SYNC and returns the same builder mock
    search_query_builder_mock.limit = MagicMock(return_value=search_query_builder_mock, name="QueryBuilderLimit_SyncMock")
    # .to_pandas_async() is ASYNC and is awaited.
    search_query_builder_mock.to_pandas_async = AsyncMock(
        return_value=pd.DataFrame({'id': [], 'text': [], 'metadata': []}), 
        name="QueryBuilderToPandas_AsyncMock"
    )

    return table_mock

@pytest_asyncio.fixture
async def mock_lancedb_connection(mock_lancedb_table): # mock_lancedb_table is the instance from above fixture
    connection = AsyncMock() 
    connection.table_names = AsyncMock(return_value=["existing_table"])
    # These should return the table_mock instance directly, as they are awaited
    connection.open_table = AsyncMock(return_value=mock_lancedb_table)
    connection.create_table = AsyncMock(return_value=mock_lancedb_table)
    return connection

@pytest_asyncio.fixture
async def mock_embedding_function():
    # Mock the embedding function object returned by the registry
    mock_func = MagicMock()
    mock_func.source_column = 'text' # Match LanceDBVectorStore implementation
    mock_func.vector_column = 'vector' # Match LanceDBVectorStore implementation
    return mock_func

@pytest_asyncio.fixture
async def lancedb_vector_store(app_config, mock_lancedb_connection, mock_embedding_function, mock_lancedb_table):
    # Patch lancedb.connect_async and the embedding registry get_instance call
    with patch('lancedb.connect_async', return_value=mock_lancedb_connection) as mock_connect_async, \
         patch('lancedb.embeddings.EmbeddingFunctionRegistry.get_instance') as mock_get_instance:
        
        # Configure the mock registry instance and the object returned by get()
        mock_registry_instance = MagicMock()
        # This mock object represents the return value of registry.get(name)
        mock_func_meta = MagicMock() 
        # The .create() method is called on this meta object, returning the actual embedding func mock
        mock_func_meta.create.return_value = mock_embedding_function 
        mock_registry_instance.get.return_value = mock_func_meta
        mock_get_instance.return_value = mock_registry_instance
        
        # Ensure the mock embedding function has ndims (used in _create_dynamic_schema)
        # and VectorField/SourceField for schema creation
        mock_embedding_function.ndims.return_value = 128 # Example dimension
        mock_embedding_function.VectorField.return_value = Field()
        mock_embedding_function.SourceField.return_value = Field()
        
        # Initialize the service synchronously (this prepares embedding_func and schema)
        service = LanceDBVectorStore(
            db_uri=app_config.memory.lancedb.uri,
            table_name=app_config.memory.lancedb.table_name
            # Default embedding func name 'openai' is used
        )
        
        # Configure the mock connection's behavior for the _initialize_table call
        mock_lancedb_connection.table_names = AsyncMock(return_value=[]) # Assume table doesn't exist initially for fixture
        # Set the return value for create_table to be the mock table instance
        mock_lancedb_connection.create_table = AsyncMock(return_value=mock_lancedb_table) 
        # Although not called in this path, set open_table for completeness
        mock_lancedb_connection.open_table = AsyncMock(return_value=mock_lancedb_table)

        # Explicitly await the async initialization step *within the patch context*
        # This should set service.db and service.table using the mocks
        await service._initialize_table()

        # Assertions to verify initialization happened as expected based on mocks
        mock_connect_async.assert_awaited_once_with(app_config.memory.lancedb.uri)
        mock_get_instance.assert_called_once() # Check registry access
        mock_registry_instance.get.assert_called_once_with("openai") # Check func lookup
        mock_func_meta.create.assert_called_once() # Check func instantiation
        mock_lancedb_connection.table_names.assert_awaited_once() # Check table existence check
        # Verify create_table was awaited since table_names returned empty
        mock_lancedb_connection.create_table.assert_awaited_once() 
        # Check schema was passed to create_table
        _, create_kwargs = mock_lancedb_connection.create_table.call_args
        assert 'schema' in create_kwargs and issubclass(create_kwargs['schema'], LanceModel)
        # Ensure open_table was NOT called in this path
        mock_lancedb_connection.open_table.assert_not_awaited() 

        # Verify that _initialize_table set the internal state correctly
        assert service.db is mock_lancedb_connection # Should be the mock connection
        assert service.table is mock_lancedb_table # Should be the mock table
        assert service._initialized is True # Flag should be set by _initialize_table

        # Yield the initialized service with mocks correctly assigned internally
        yield service
        
        # Teardown if needed (optional close)
        # If close() is async and interacts with mocks, ensure it's awaited
        if hasattr(service, 'close') and asyncio.iscoroutinefunction(service.close):
           await service.close()

# Test initialization variations (Now tests _initialize_table directly)
@pytest.mark.parametrize("table_exists, expected_call", [
    (True, "open_table"),
    (False, "create_table")
])
@pytest.mark.asyncio
async def test_init_opens_or_creates_table(table_exists, expected_call, app_config, mock_lancedb_connection, mock_embedding_function, mock_lancedb_table):
    """Verify that the correct async method (open_table or create_table) is called based on table existence."""
    table_name = app_config.memory.lancedb.table_name
    # Adjust mock_lancedb_connection based on the parameter
    if table_exists:
        mock_lancedb_connection.table_names = AsyncMock(return_value=[table_name])
    else:
        mock_lancedb_connection.table_names = AsyncMock(return_value=[])

    # Mock the table returned by create/open
    mock_lancedb_connection.create_table.return_value = mock_lancedb_table # Use injected fixture
    mock_lancedb_connection.open_table.return_value = mock_lancedb_table # Use injected fixture

    with patch('lancedb.connect_async', return_value=mock_lancedb_connection), \
         patch('lancedb.embeddings.EmbeddingFunctionRegistry.get_instance') as mock_get_instance:
        
        mock_registry_instance = MagicMock()
        # Mock the create method on the object returned by get()
        mock_func_meta = MagicMock()
        mock_func_meta.create.return_value = mock_embedding_function 
        mock_registry_instance.get.return_value = mock_func_meta
        mock_get_instance.return_value = mock_registry_instance

        # Mock embedding func attributes needed for schema creation
        mock_embedding_function.ndims.return_value = 128
        mock_embedding_function.VectorField.return_value = Field()
        mock_embedding_function.SourceField.return_value = Field()

        # Create instance (sync init part)
        service = LanceDBVectorStore(
            db_uri=app_config.memory.lancedb.uri, 
            table_name=table_name
        )
        # Call the async initialization part
        await service._initialize_table()
        
        # Assert the correct method was called on the connection
        mock_lancedb_connection.table_names.assert_awaited_once()
        if expected_call == "open_table":
            mock_lancedb_connection.open_table.assert_awaited_once_with(table_name)
            mock_lancedb_connection.create_table.assert_not_awaited()
        else:
            mock_lancedb_connection.create_table.assert_awaited_once()
            # Check args of create_table (name, schema, mode)
            args, kwargs = mock_lancedb_connection.create_table.call_args
            assert args[0] == table_name
            # Schema check might be more involved, checking type or key fields
            assert 'schema' in kwargs and issubclass(kwargs['schema'], LanceModel)
            assert kwargs.get('mode') == 'create' # Default mode
            mock_lancedb_connection.open_table.assert_not_awaited()

@pytest.mark.asyncio
async def test_write_success(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock):
    key = "doc1"
    text = "This is the document text."
    metadata = {"source": "test", "timestamp": 12345}
    # The schema uses 'doc_id'
    expected_data = [{
        "doc_id": key,
        "text": text,
        "metadata": json.dumps(metadata)
    }]

    await lancedb_vector_store.write(key, text, metadata)

    # Check that table.add was called with the correctly formatted data
    mock_lancedb_table.add.assert_awaited_once()
    call_args, call_kwargs = mock_lancedb_table.add.call_args
    # The first argument should be the data (list of dicts)
    assert isinstance(call_args[0], list)
    assert len(call_args[0]) == 1
    # Compare the dictionary content (handle potential JSON string diff)
    added_dict = call_args[0][0]
    assert added_dict['doc_id'] == expected_data[0]['doc_id']
    assert added_dict['text'] == expected_data[0]['text']
    # Metadata comparison: deserialize from JSON string if needed
    if isinstance(added_dict['metadata'], str):
         assert json.loads(added_dict['metadata']) == json.loads(expected_data[0]['metadata'])
    else:
         assert added_dict['metadata'] == expected_data[0]['metadata']

@pytest.mark.asyncio
async def test_read_success_found(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock):
    key = "doc_to_find"
    expected_text = "Found this text."
    expected_metadata = {"found": True}
    expected_filter_str = f"doc_id = '{key}'" # Use doc_id

    # Configure the mock chain to return a DataFrame with one row
    mock_df = pd.DataFrame([{
        'doc_id': key, # Use doc_id in mock data if needed for consistency
        'text': expected_text,
        'metadata': json.dumps(expected_metadata)
    }])
    
    # Configure the mock return value *without* calling search() again
    search_builder_mock = mock_lancedb_table.search.return_value
    search_builder_mock.where.return_value.limit.return_value.to_pandas_async.return_value = mock_df

    result = await lancedb_vector_store.read(key)

    # Verify the search call chain was used correctly
    mock_lancedb_table.search.assert_called_once() # search() is sync
    # Get the mock builder instance that search() returned
    search_builder_instance = mock_lancedb_table.search.return_value
    search_builder_instance.where.assert_called_once_with(expected_filter_str)
    search_builder_instance.where.return_value.limit.assert_called_once_with(1)
    search_builder_instance.where.return_value.limit.return_value.to_pandas_async.assert_awaited_once()

    assert result is not None
    assert result.get("text") == expected_text
    assert result.get("metadata") == expected_metadata

@pytest.mark.asyncio
async def test_read_success_not_found(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock):
    key = "doc_not_found"
    expected_filter_str = f"doc_id = '{key}'" # Use doc_id

    # Configure the mock chain to return an empty DataFrame
    mock_df = pd.DataFrame({'doc_id': [], 'text': [], 'metadata': []}) # Use doc_id
    # Configure the mock return value *without* calling search() again
    search_builder_mock = mock_lancedb_table.search.return_value
    search_builder_mock.where.return_value.limit.return_value.to_pandas_async.return_value = mock_df

    result = await lancedb_vector_store.read(key)

    # Verify the search call chain was used correctly
    mock_lancedb_table.search.assert_called_once() # search() is sync
    # Get the mock builder instance that search() returned
    search_builder_instance = mock_lancedb_table.search.return_value
    search_builder_instance.where.assert_called_once_with(expected_filter_str)
    search_builder_instance.where.return_value.limit.assert_called_once_with(1)
    search_builder_instance.where.return_value.limit.return_value.to_pandas_async.assert_awaited_once()

    assert result is None

@pytest.mark.asyncio
async def test_delete_success(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock):
    key = "doc_to_delete"
    # Implementation uses doc_id in filter string
    expected_filter = f"doc_id = '{key}'" 

    await lancedb_vector_store.delete(key)

    # Check that table.delete was called with the correct filter string
    mock_lancedb_table.delete.assert_awaited_once_with(expected_filter)

@pytest.mark.asyncio
async def test_search_success(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock):
    query = "search query text"
    top_k = 3
    expected_results_data = [
        # Use doc_id for consistency if needed, though not checked directly here
        {'doc_id': 'res1', 'text': 'Result 1', 'metadata': json.dumps({"source": "A"}), '_distance': 0.1},
        {'doc_id': 'res2', 'text': 'Result 2', 'metadata': json.dumps({"source": "B"}), '_distance': 0.2}
    ]
    mock_df = pd.DataFrame(expected_results_data)

    # Configure the mock chain for search
    # Configure the mock return value *without* calling search() again
    search_builder_mock = mock_lancedb_table.search.return_value
    # Note: search() takes query arg, where() is not called for basic search
    search_builder_mock.limit.return_value.to_pandas_async.return_value = mock_df

    results = await lancedb_vector_store.search(query=query, top_k=top_k)

    # Verify the search call chain
    mock_lancedb_table.search.assert_called_once_with(query)
    # Get the mock builder instance that search() returned
    search_builder_instance = mock_lancedb_table.search.return_value
    search_builder_instance.where.assert_not_called() # No filter applied
    search_builder_instance.limit.assert_called_once_with(top_k)
    search_builder_instance.limit.return_value.to_pandas_async.assert_awaited_once()

    # Check results formatting
    assert len(results) == 2
    assert results[0]['text'] == 'Result 1'
    assert results[0]['metadata'] == {"source": "A"} # Check deserialized metadata
    assert results[0]['score'] == 0.1 # Check score mapping
    assert results[1]['text'] == 'Result 2'
    assert results[1]['metadata'] == {"source": "B"}
    assert results[1]['score'] == 0.2

@pytest.mark.asyncio
async def test_search_with_filters(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock):
    query = "filtered search"
    top_k = 2
    # Use metadata fields directly for filter building in LanceDBVectorStore
    filters = {"source": "specific", "timestamp": {"$gt": 1000}} 
    # Construct expected SQL-like filter string based on implementation
    # Assuming simple AND for now, adjust if implementation is different
    expected_filter_str = "metadata['source'] = 'specific' AND metadata['timestamp'] > 1000" 

    expected_results_data = [
        {'doc_id': 'f_res1', 'text': 'Filtered Result 1', 'metadata': json.dumps({"source": "specific", "timestamp": 1500}), '_distance': 0.3}
    ]
    mock_df = pd.DataFrame(expected_results_data)

    # Configure the mock chain for filtered search
    # Configure the mock return value *without* calling search() again
    search_builder_mock = mock_lancedb_table.search.return_value
    search_builder_mock.where.return_value.limit.return_value.to_pandas_async.return_value = mock_df
    
    # Mock the internal filter builder if needed, or just check the where() call
    with patch.object(lancedb_vector_store, '_build_filter_string', return_value=expected_filter_str) as mock_build_filter:
        results = await lancedb_vector_store.search(query=query, top_k=top_k, filters=filters)

    # Verify the search call chain
    mock_lancedb_table.search.assert_called_once_with(query)
    # Verify filter builder was called
    mock_build_filter.assert_called_once_with(filters)
    # Get the mock builder instance that search() returned
    search_builder_instance = mock_lancedb_table.search.return_value
    # Check where() was called with the expected string from the (mocked) builder
    search_builder_instance.where.assert_called_once_with(expected_filter_str, prefilter=False) 
    search_builder_instance.where.return_value.limit.assert_called_once_with(top_k)
    search_builder_instance.where.return_value.limit.return_value.to_pandas_async.assert_awaited_once()

    # Check results formatting
    assert len(results) == 1
    assert results[0]['text'] == 'Filtered Result 1'
    assert results[0]['metadata'] == {"source": "specific", "timestamp": 1500}
    assert results[0]['score'] == 0.3

# TODO: Add tests for error_handling (e.g., LanceDBConnectionError) 
# --- Error Handling Tests ---

# Import specific LanceDB exception if known, otherwise use a generic Exception
# from lancedb.exceptions import LanceDBError # Example
import lancedb # Assume LanceDBError exists or use generic Exception

@pytest.mark.asyncio
async def test_write_failure(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock, caplog):
    """Test that write failures are logged and don't raise exceptions."""
    key = "fail_doc"
    text = "This will fail."
    metadata = {"source": "failure_test"}
    # Configure mock to raise an error on add()
    mock_lancedb_table.add.side_effect = Exception("Simulated write error")
    # Also configure delete mock in case it's called first in upsert
    mock_lancedb_table.delete.side_effect = Exception("Simulated delete error during upsert")

    import logging
    caplog.set_level(logging.ERROR)

    # Write should handle the exception internally and log it
    # It should not raise an exception itself, as it catches the re-raised one from delete()
    await lancedb_vector_store.write(key, text, metadata)

    # Check which mock actually raised the error based on implementation (delete first)
    mock_lancedb_table.delete.assert_awaited_once()
    mock_lancedb_table.add.assert_not_awaited() # Add should not be reached if delete fails

    # Assert the correct error message is logged (from the write() method's except block)
    assert f"Failed during upsert operation for doc_id '{key}'" in caplog.text
    # Check that the specific error message from the delete side_effect is also present
    assert "Simulated delete error during upsert" in caplog.text

@pytest.mark.asyncio
async def test_read_failure(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock, caplog):
    """Test that read failures return None and log errors."""
    key = "fail_read_doc"
    # Configure search chain to raise an error
    # Configure the mock return value *without* calling search() again
    search_builder_mock = mock_lancedb_table.search.return_value
    search_builder_mock.where.return_value.limit.return_value.to_pandas_async.side_effect = Exception("Simulated read error")

    import logging
    caplog.set_level(logging.ERROR)

    result = await lancedb_vector_store.read(key)

    # Assert search chain was called up to the point of failure
    mock_lancedb_table.search.assert_called_once()
    search_builder_instance = mock_lancedb_table.search.return_value
    search_builder_instance.where.assert_called_once_with(f"doc_id = '{key}'")
    search_builder_instance.where.return_value.limit.assert_called_once_with(1)
    search_builder_instance.where.return_value.limit.return_value.to_pandas_async.assert_awaited_once()

    assert result is None # Should return None on failure
    # Assert the correct error message is logged
    assert f"Failed to read doc_id '{key}'" in caplog.text
    assert "Simulated read error" in caplog.text

@pytest.mark.asyncio
async def test_delete_failure(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock, caplog):
    """Test that delete failures are logged and re-raised."""
    key = "fail_delete_doc"
    expected_filter = f"doc_id = '{key}'" # Use doc_id
    # Configure mock to raise an error
    simulated_exception = Exception("Simulated delete error")
    mock_lancedb_table.delete.side_effect = simulated_exception

    import logging
    caplog.set_level(logging.ERROR)

    # Expect the specific exception to be raised
    with pytest.raises(Exception, match="Simulated delete error"):
        await lancedb_vector_store.delete(key)

    # Ensure delete was called with correct filter before raising
    mock_lancedb_table.delete.assert_awaited_once_with(expected_filter) 

    # Assert the correct error message is logged by the delete() method itself
    assert f"Failed to delete doc_id '{key}'" in caplog.text
    assert "Simulated delete error" in caplog.text

@pytest.mark.asyncio
async def test_search_failure(lancedb_vector_store: LanceDBVectorStore, mock_lancedb_table: AsyncMock, caplog):
    """Test that search failures return empty list and log errors."""
    query = "fail search query"
    top_k = 3
    # Configure search chain to raise an error
    # Configure the mock return value *without* calling search() again
    search_builder_mock = mock_lancedb_table.search.return_value
    search_builder_mock.limit.return_value.to_pandas_async.side_effect = Exception("Simulated search error")

    import logging
    caplog.set_level(logging.ERROR)

    results = await lancedb_vector_store.search(query=query, top_k=top_k)

    # Assert search chain was called up to the point of failure
    mock_lancedb_table.search.assert_called_once_with(query)
    search_builder_instance = mock_lancedb_table.search.return_value
    search_builder_instance.where.assert_not_called() # No filter
    search_builder_instance.limit.assert_called_once_with(top_k)
    search_builder_instance.limit.return_value.to_pandas_async.assert_awaited_once()

    assert results == [] # Should return empty list on failure
    # Assert the correct error message is logged
    assert f"Failed to execute search for query '{query}'" in caplog.text
    assert "Simulated search error" in caplog.text

# TODO: Add test for initialization failure (e.g., lancedb.connect error)
# This might require adjusting the fixture structure slightly. 