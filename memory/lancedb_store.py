import asyncio
import json
import logging
from typing import Any, List, Dict, Optional, Type

import lancedb
import pyarrow as pa
from lancedb.pydantic import LanceModel, Vector
from lancedb.embeddings import get_registry, EmbeddingFunctionRegistry, EmbeddingFunction
from pydantic import Field, BaseModel
import structlog

from .base import MemoryService

log = structlog.get_logger(__name__)

# Define a base model for data records without vector field initially
class BaseLanceRecord(BaseModel):
    text: str
    doc_id: str
    metadata: Optional[str] = None

class LanceDBVectorStore(MemoryService):
    """Vector store implementation using LanceDB with built-in embeddings."""

    def __init__(
        self,
        db_uri: str,
        table_name: str,
        embedding_function_name: str = "openai", # e.g., "openai", "sentence-transformers"
        embedding_model_name: Optional[str] = None, # e.g., "text-embedding-ada-002", "BAAI/bge-small-en-v1.5"
        # Add kwargs for embedding function config if needed (e.g., api_key_env_var for openai)
    ):
        """
        Initialize the LanceDB vector store using its built-in embedding functions.

        Args:
            db_uri: Path or URI for the LanceDB database.
            table_name: Name of the table to use/create.
            embedding_function_name: Name of the embedding function in LanceDB registry.
            embedding_model_name: Specific model name for the embedding function.
        """
        self.db_uri = db_uri
        self.table_name = table_name
        self.embedding_function_name = embedding_function_name
        self.embedding_model_name = embedding_model_name
        self.db = None
        self.table = None
        self.embedding_func = None
        self.schema = None # Schema will be created after embedding_func is initialized
        self._initialized = False # Flag to track initialization

        try:
            # Initialize embedding function synchronously if possible
            # (LanceDB registry/create might be sync)
            registry = EmbeddingFunctionRegistry.get_instance()
            try:
                func_meta = registry.get(self.embedding_function_name)
            except Exception as e:
                func_names = list(registry.keys()) if hasattr(registry, 'keys') else []
                log.error(f"Embedding function '{self.embedding_function_name}' not found. Available: {func_names}. Error: {e}")
                raise ValueError(f"Embedding function '{self.embedding_function_name}' not found.") from e

            # Pass model name if provided
            create_kwargs = {}
            if self.embedding_model_name:
                create_kwargs['name'] = self.embedding_model_name
            # TODO: Add mechanism to pass API keys or other config to create() if needed,
            # potentially via environment variables checked by LanceDB or passed kwargs.
            # Example for OpenAI: ensure OPENAI_API_KEY is set in environment.
            self.embedding_func = func_meta.create(**create_kwargs)
            self.schema = self._create_dynamic_schema()
            log.info(f"Initialized LanceDB embedding function '{self.embedding_function_name}' and schema.")

        except Exception as e:
            log.error(f"Failed to initialize LanceDB embedding function or schema: {e}", exc_info=True)
            # We don't raise here, let _initialize_table handle connection errors later
            self.embedding_func = None
            self.schema = None

    async def _initialize_table(self):
        """Asynchronously connect to DB and open or create the table."""
        if self._initialized:
            return
            
        if not self.embedding_func or not self.schema:
             log.error("Cannot initialize LanceDB table: Embedding function or schema not ready.")
             raise RuntimeError("LanceDB embedding function or schema failed to initialize.")

        try:
            log.info(f"Connecting to LanceDB at: {self.db_uri}")
            # lancedb.connect returns an AsyncConnection
            self.db = await lancedb.connect_async(self.db_uri)
            
            log.info(f"Checking for LanceDB table: {self.table_name}")
            table_names = await self.db.table_names()
            
            if self.table_name in table_names:
                log.info(f"Opening existing LanceDB table: {self.table_name}")
                self.table = await self.db.open_table(self.table_name)
                # TODO: Potentially validate schema compatibility here?
            else:
                log.info(f"Creating new LanceDB table: {self.table_name} with schema: {self.schema.__name__}")
                self.table = await self.db.create_table(
                    self.table_name, 
                    schema=self.schema, 
                    mode="create"
                )
            
            self._initialized = True
            log.info(f"LanceDB table '{self.table_name}' initialized successfully.")

        except Exception as e:
            log.error(f"Failed to initialize LanceDB table '{self.table_name}'. Error: {e}", exc_info=True)
            self._initialized = False # Ensure flag is false on error
            self.db = None
            self.table = None
            # Optionally re-raise or handle differently
            raise RuntimeError(f"Failed to initialize LanceDB table '{self.table_name}'") from e

    async def _ensure_initialized(self):
        """Helper to ensure the table is initialized before operations."""
        if not self._initialized:
            await self._initialize_table()
        if not self.table:
             # This should not happen if _initialize_table succeeded or raised
             raise RuntimeError("LanceDB table is not available after initialization attempt.")

    def _create_dynamic_schema(self) -> Type[LanceModel]:
        """Creates a dynamic Pydantic schema linked to the embedding function."""
        if not self.embedding_func:
             raise RuntimeError("Embedding function not initialized before creating schema.")

        # Capture embedding_func and dimension in local variables
        embedding_func = self.embedding_func 
        embedding_dim = embedding_func.ndims() 
        # source_field_name = "text" # Not strictly needed if using SourceField()

        # Use a factory function to define the class dynamically
        class DynamicLanceSchema(LanceModel):
            # Use the local variables captured above, not self.
            vector: Vector(embedding_dim) = embedding_func.VectorField() 
            text: str = embedding_func.SourceField()
            doc_id: str # Add doc_id separately as it's not part of embedding
            metadata: Optional[str] = None

            # If LanceModel base class doesn't handle extra fields, use BaseModel
            # and potentially add vector later or use PyArrow schema.
            # For now, assume LanceModel works like this.
        
        # This dynamic creation might need refinement based on LanceModel internals
        # It might be better to construct a PyArrow schema manually here.
        log.info(f"Created dynamic LanceDB schema with dim {embedding_dim} linked to func {self.embedding_function_name}")
        return DynamicLanceSchema

    # --- MemoryService Interface Implementation (Revised) ---

    async def write(self, key: str, value: Any, metadata: Optional[Dict] = None, ttl: Optional[int] = None) -> None:
        """Writes (upserts) data; LanceDB handles embedding via schema."""
        await self._ensure_initialized()
        if not self.table:
            log.error("LanceDB table not initialized, cannot write.")
            return
        if ttl:
            log.warning(f"LanceDBVectorStore does not support TTL for key '{key}'")

        if not isinstance(value, str):
            log.error(f"LanceDBVectorStore.write currently only supports string values for embedding. Received type {type(value)}.")
            return
        
        metadata_str = json.dumps(metadata) if metadata else None
        # Prepare record matching schema fields *excluding* vector (it's auto-generated)
        # Ensure doc_id is included.
        data_record = {
            "doc_id": key,
            "text": value, 
            "metadata": metadata_str
        }
            
        try:
            # Upsert: Delete + Add
            log.debug(f"Attempting delete for upsert: doc_id = '{key}'")
            await self.delete(key) # Call delete helper which has its own logging
            
            # If delete succeeded, proceed to add
            log.debug(f"Attempting add for upsert: doc_id = '{key}'")
            await self.table.add([data_record]) # LanceDB computes embedding for 'text'
            log.debug(f"Successfully upserted doc_id '{key}' via LanceDB embedding function.")
        
        except Exception as e:
            # This will catch errors from either delete() or table.add()
            # delete() already logs its specific errors, so we log a general upsert failure here.
            log.error(f"Failed during upsert operation for doc_id '{key}': {e}", exc_info=True)
            # No need to log duplicate info if delete() failed and logged.
            # The error 'e' will contain the specific exception (from delete or add).

    async def read(self, key: str) -> Optional[Dict[str, Any]]:
        # Read implementation remains largely the same, fetches by doc_id
        await self._ensure_initialized()
        if not self.table:
            log.error("LanceDB table not initialized.")
            return None
        try:
            results = await self.table.search().where(f"doc_id = '{key}'").limit(1).to_pandas_async()
            if results.empty: return None
            doc = results.iloc[0].to_dict()
            output = {"text": doc.get("text"), "metadata": None}
            if doc.get("metadata"):
                try: output["metadata"] = json.loads(doc["metadata"])
                except: output["metadata"] = doc["metadata"]
            return output
        except Exception as e:
            log.error(f"Failed to read doc_id '{key}': {e}", exc_info=True)
            return None

    async def delete(self, key: str) -> None:
        # Delete implementation remains the same
        await self._ensure_initialized()
        if not self.table: return
        try:
            await self.table.delete(f"doc_id = '{key}'")
            log.debug(f"Successfully deleted doc_id '{key}'")
        except Exception as e:
            log.error(f"Failed to delete doc_id '{key}': {e}", exc_info=True)
            raise # Re-raise the exception after logging

    async def search(self, query: str, top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        """Performs vector search; LanceDB handles query embedding via schema/function."""
        await self._ensure_initialized()
        if not self.table:
            log.error("LanceDB table not initialized, cannot search.")
            return []

        try:
            # LanceDB handles query embedding if table was created with embedding func
            search_query = self.table.search(query) 

            if filters:
                filter_string = self._build_filter_string(filters)
                if filter_string:
                     # Still need filter string builder
                    search_query = search_query.where(filter_string, prefilter=False)

            results = await search_query.limit(top_k).to_pandas_async()

            # Format results (remains same)
            output_list = []
            for doc in results.to_dict(orient='records'):
                formatted_doc = {
                    "text": doc.get("text"),
                    "metadata": None,
                    "score": doc.get("_distance")
                }
                if doc.get("metadata"):
                    try: formatted_doc["metadata"] = json.loads(doc["metadata"])
                    except: formatted_doc["metadata"] = doc["metadata"]
                output_list.append(formatted_doc)
            return output_list

        except Exception as e:
            log.error(f"Failed to execute search for query '{query}': {e}", exc_info=True)
            return []

    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        # Filter string builder remains the same
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                escaped_value = value.replace("'", "''")
                conditions.append(f"json_extract(metadata, '$.{key}') = '{escaped_value}'")
            elif isinstance(value, (int, float, bool)):
                sql_value = str(value).upper() if isinstance(value, bool) else str(value)
                conditions.append(f"CAST(json_extract(metadata, '$.{key}') AS REAL) = {sql_value}")
            else:
                log.warning(f"Unsupported filter type {type(value)} for key '{key}'. Skipping.")
        return " AND ".join(conditions)

    async def close(self):
        log.info("LanceDB connection close requested (currently no-op).")
        pass 