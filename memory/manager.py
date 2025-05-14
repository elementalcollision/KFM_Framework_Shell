import structlog
from typing import Any, List, Dict, Optional
from contextlib import asynccontextmanager

from core.config import AppConfig
from .base import MemoryService
from .redis_cache import RedisCacheService
from .lancedb_store import LanceDBVectorStore

log = structlog.get_logger(__name__)

class MemoryManager(MemoryService):
    """Manages interaction between cache and persistent vector store."""

    def __init__(
        self,
        cache_service: Optional[RedisCacheService] = None,
        vector_stores: Optional[Dict[str, LanceDBVectorStore]] = None
    ):
        self.cache_service = cache_service
        self._vector_stores = vector_stores if vector_stores else {}
        self._log_status()

    def _log_status(self):
        if self.cache_service:
            log.info(f"MemoryManager: RedisCacheService is active.")
        else:
            log.info(f"MemoryManager: RedisCacheService is INACTIVE.")
        
        if self._vector_stores:
            log.info(f"MemoryManager: {len(self._vector_stores)} LanceDBVectorStore(s) configured: {list(self._vector_stores.keys())}")
        else:
            log.info(f"MemoryManager: LanceDBVectorStore is INACTIVE.")

    def get_cache_service(self) -> Optional[RedisCacheService]:
        """Returns the configured cache service instance."""
        return self.cache_service

    async def get_vector_store(self, store_id: str = 'default') -> Optional[LanceDBVectorStore]:
        """Returns a specific configured vector store instance by ID."""
        store = self._vector_stores.get(store_id)
        if store and not store._initialized: # Ensure it's initialized
            try:
                await store._ensure_initialized()
            except Exception:
                log.exception(f"Failed to ensure vector store '{store_id}' is initialized.")
                return None # Treat as unavailable if init fails
        return store

    async def write(self, key: str, value: Any, metadata: Optional[Dict] = None, ttl: Optional[int] = None, vector_store_id: str = 'default') -> None:
        """
        Writes to the specified vector store and then caches if cache is enabled.
        TTL is primarily for the cache.
        Value for vector store is assumed to be text for embedding.
        """
        vector_store = await self.get_vector_store(vector_store_id)
        if vector_store:
            try:
                await vector_store.write(key, value, metadata) # Vector store handles embedding
                log.debug(f"MemoryManager: Wrote key '{key}' to vector store '{vector_store_id}'.")
            except Exception as e:
                log.error(f"MemoryManager: Error writing key '{key}' to vector store '{vector_store_id}': {e}", exc_info=True)
                # Optionally re-raise or handle so cache write isn't skipped if critical

        if self.cache_service:
            try:
                # Cache the original value (text) and its metadata
                cache_value = {"text": value, "metadata": metadata}
                await self.cache_service.write(key, cache_value, ttl=ttl)
                log.debug(f"MemoryManager: Wrote key '{key}' to cache.")
            except Exception as e:
                log.error(f"MemoryManager: Error writing key '{key}' to cache: {e}", exc_info=True)

    async def read(self, key: str, vector_store_id: str = 'default') -> Optional[Dict[str, Any]]: # Return type matches LanceDB read
        """
        Reads from cache first. If not found, reads from the specified vector store and caches the result.
        Returns a dict containing 'text' and 'metadata'.
        """
        if self.cache_service:
            try:
                cached_data = await self.cache_service.read(key)
                if cached_data is not None and isinstance(cached_data, dict) and "text" in cached_data:
                    log.debug(f"MemoryManager: Read key '{key}' from cache.")
                    return cached_data # Expected to be a dict {"text": ..., "metadata": ...}
            except Exception as e:
                log.error(f"MemoryManager: Error reading key '{key}' from cache: {e}", exc_info=True)

        vector_store = await self.get_vector_store(vector_store_id)
        if vector_store:
            try:
                vector_store_data = await vector_store.read(key)
                if vector_store_data:
                    log.debug(f"MemoryManager: Read key '{key}' from vector store '{vector_store_id}'.")
                    # Cache this result if cache is enabled
                    if self.cache_service:
                        try:
                            # Cache expects value and metadata. VS returns a dict {"text": ..., "metadata": ...}
                            # Use default TTL from cache service if available
                            default_ttl = getattr(self.cache_service, 'default_ttl', None)
                            await self.cache_service.write(key, vector_store_data, ttl=default_ttl)
                            log.debug(f"MemoryManager: Cached key '{key}' from vector store read.")
                        except Exception as e_cache_write:
                            log.error(f"MemoryManager: Error caching key '{key}' after vector store read: {e_cache_write}", exc_info=True)
                    return vector_store_data
            except Exception as e:
                log.error(f"MemoryManager: Error reading key '{key}' from vector store '{vector_store_id}': {e}", exc_info=True)
        
        log.debug(f"MemoryManager: Key '{key}' not found in cache or vector store '{vector_store_id}'.")
        return None

    async def search(self, query: str, top_k: int = 5, filters: Optional[Dict] = None, vector_store_id: str = 'default') -> List[Dict]:
        """Performs search directly on the specified vector store. Cache is not used for search results."""
        vector_store = await self.get_vector_store(vector_store_id)
        if vector_store:
            try:
                results = await vector_store.search(query, top_k, filters)
                log.debug(f"MemoryManager: Search for '{query}' returned {len(results)} results from vector store '{vector_store_id}'.")
                return results
            except Exception as e:
                log.error(f"MemoryManager: Error during search for '{query}' in vector store '{vector_store_id}': {e}", exc_info=True)
        
        log.warning(f"MemoryManager: Vector store '{vector_store_id}' unavailable for search query '{query}'.")
        return []

    async def delete(self, key: str, vector_store_id: str = 'default') -> None:
        """Deletes from the specified vector store and the cache."""
        vector_store = await self.get_vector_store(vector_store_id)
        if vector_store:
            try:
                await vector_store.delete(key)
                log.debug(f"MemoryManager: Deleted key '{key}' from vector store '{vector_store_id}'.")
            except Exception as e:
                log.error(f"MemoryManager: Error deleting key '{key}' from vector store '{vector_store_id}': {e}", exc_info=True)

        if self.cache_service:
            try:
                await self.cache_service.delete(key)
                log.debug(f"MemoryManager: Deleted key '{key}' from cache.")
            except Exception as e:
                log.error(f"MemoryManager: Error deleting key '{key}' from cache: {e}", exc_info=True)

    async def close(self) -> None:
        """Closes underlying services if they have close methods."""
        if self.cache_service and hasattr(self.cache_service, 'close') and callable(self.cache_service.close):
            try: # Add try/except for robustness
                await self.cache_service.close()
            except Exception:
                log.exception("Error closing cache service")

        for store_id, store in self._vector_stores.items():
            if store and hasattr(store, 'close') and callable(store.close):
                try:
                    await store.close()
                except Exception:
                    log.exception(f"Error closing vector store '{store_id}'")
        log.info("MemoryManager closed underlying services.")

# --- Lifespan Manager ---

@asynccontextmanager
async def memory_lifespan(config: AppConfig):
    """
    Async context manager to initialize and clean up memory services.
    Creates MemoryManager and attaches it to app.state.memory_manager.
    """
    cache_service = None
    vector_stores = {}
    memory_manager = None

    # Initialize Cache Service
    if config.memory.redis_enabled and config.redis:
        try:
            cache_service = RedisCacheService(redis_url=config.redis.url, default_ttl=config.memory.cache_ttl_seconds)
            log.info(f"Redis Cache Service initialized: {config.redis.url}")
        except Exception as e:
            log.error(f"Failed to initialize Redis Cache Service: {e}", exc_info=True)
            cache_service = None # Ensure it's None if init fails
    else:
        log.info("Redis Cache Service is disabled in config.")

    # Initialize Vector Store(s)
    if config.memory.vector_store_enabled and config.memory.lancedb:
        lancedb_configs = config.memory.lancedb
        if isinstance(lancedb_configs, dict): # Multiple stores configured
            for store_id, store_config in lancedb_configs.items():
                try:
                    store = LanceDBVectorStore(
                        db_uri=store_config.uri,
                        table_name=store_config.table_name,
                        embedding_function_name=store_config.embedding_function_name,
                        embedding_model_name=store_config.embedding_model_name
                    )
                    await store._initialize_table() # Await async initialization
                    vector_stores[store_id] = store
                    log.info(f"LanceDB Vector Store '{store_id}' initialized: {store_config.uri}")
                except Exception as e:
                    log.error(f"Failed to initialize LanceDB Vector Store '{store_id}': {e}", exc_info=True)
        elif isinstance(lancedb_configs, object) and hasattr(lancedb_configs, 'uri'): # Single store
             store_id = 'default' # Or derive from config if needed
             try:
                 store = LanceDBVectorStore(
                     db_uri=lancedb_configs.uri,
                     table_name=lancedb_configs.table_name,
                     embedding_function_name=lancedb_configs.embedding_function_name,
                     embedding_model_name=lancedb_configs.embedding_model_name
                 )
                 await store._initialize_table()
                 vector_stores[store_id] = store
                 log.info(f"LanceDB Vector Store '{store_id}' initialized: {lancedb_configs.uri}")
             except Exception as e:
                 log.error(f"Failed to initialize LanceDB Vector Store '{store_id}': {e}", exc_info=True)
        else:
             log.warning("LanceDB config found but format is unrecognized (expected dict or single object with uri).")
    else:
        log.info("LanceDB Vector Store is disabled or not configured.")

    # Create MemoryManager
    memory_manager = MemoryManager(cache_service=cache_service, vector_stores=vector_stores)

    # Yield control to the application, passing the manager via a placeholder object
    # The actual app object isn't available here, so the caller needs to attach.
    class AppStatePlaceholder:
        def __init__(self):
            self.memory_manager = memory_manager

    try:
        yield AppStatePlaceholder() # Pass the manager container
    finally:
        # Cleanup: Close services
        log.info("Closing memory services...")
        if memory_manager:
            await memory_manager.close() 