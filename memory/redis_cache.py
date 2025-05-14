import json
import logging
from typing import Any, List, Dict, Optional

import redis.asyncio
from redis.exceptions import RedisError
from contextlib import asynccontextmanager
import structlog

from .base import MemoryService

log = structlog.get_logger(__name__)

class RedisCacheService(MemoryService):
    """A memory service implementation using Redis for caching key-value data."""

    def __init__(self, redis_url: str, default_ttl: Optional[int] = 3600):
        """
        Initialize the Redis connection pool.

        Args:
            redis_url: The connection URL for the Redis instance.
            default_ttl: The default TTL for cached items.
        """
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        try:
            # Corrected initialization - use Redis.from_url not asyncio.from_url
            self.redis_client = redis.asyncio.Redis.from_url(self.redis_url, decode_responses=True)
            log.info(f"RedisCacheService initialized for URL: {self.redis_url} with default TTL: {self.default_ttl}")
        except Exception as e:
            log.error(f"Failed to initialize Redis client: {e}", exc_info=True)
            self.redis_client = None # Ensure it's None if init fails

    async def _execute_redis_command(self, command_name: str, *args: Any, **kwargs: Any) -> Any:
        """Helper to execute a Redis command with error handling."""
        if not self.redis_client:
            log.error("Redis client not available for command execution.")
            return None # Or raise an exception
        
        try:
            # Get the method from the client instance
            method_to_call = getattr(self.redis_client, command_name)
            # Await the command directly on the client
            return await method_to_call(*args, **kwargs)
        except RedisError as e:
            log.error(f"Redis error on {command_name}({args}, {kwargs}): {e}", exc_info=True)
            return None
        except Exception as e:
            log.error(f"Unexpected error on {command_name}({args}, {kwargs}): {e}", exc_info=True)
            return None

    async def write(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Write data to Redis cache with optional TTL.
        
        Args:
            key: The key for the data.
            value: The value to store.
            ttl: Time-to-live in seconds. If None, uses the default TTL.
        """
        try:
            # Always JSON serialize the value for consistent storage format
            serialized_value = json.dumps(value)
        except (TypeError, ValueError) as e:
            log.error(f"Failed to serialize value for key '{key}': {e}")
            return
            
        # Use provided TTL or fall back to default
        actual_ttl = ttl if ttl is not None else self.default_ttl
        
        # Always include the ex parameter with the TTL value
        success = await self._execute_redis_command(
            'set', key, serialized_value, ex=actual_ttl
        )
        
        if success:
            log.debug(f"Successfully wrote key '{key}' to cache with TTL {actual_ttl}s")
        else:
            log.warning(f"Failed to write key '{key}' to cache")

    async def read(self, key: str) -> Optional[Any]:
        """
        Read data from Redis cache. Deserializes value from JSON.
        """
        serialized_value = await self._execute_redis_command('get', key)
        if serialized_value is None:
            log.debug(f"Key '{key}' not found in Redis cache.")
            return None

        try:
            return json.loads(serialized_value)
        except json.JSONDecodeError as e:
            log.error(f"Failed to deserialize JSON from Redis for key '{key}': {e}", exc_info=True)
            return None # Treat corrupted data as missing
        except Exception as e:
            log.error(f"Unexpected error deserializing data for key '{key}': {e}", exc_info=True)
            return None

    async def delete(self, key: str) -> None:
        """
        Delete data from Redis cache by key.
        """
        deleted_count = await self._execute_redis_command('delete', key)
        # In tests, deleted_count might be a mock, so handle both cases
        if deleted_count is not None:
            if isinstance(deleted_count, int) and deleted_count > 0:
                log.debug(f"Successfully deleted key '{key}' from cache")
            else:
                log.debug(f"Key '{key}' was not found in cache")

    async def search(self, query: str, top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        """
        Search functionality is not supported by the Redis cache.
        Returns an empty list.
        """
        log.warning("Search operation called on RedisCacheService, which is not supported. Returning empty list.")
        return []

    async def close(self) -> None:
        """
        Close the Redis connection.
        """
        if self.redis_client:
            try:
                # Ensure we await the close method
                await self.redis_client.close()
                log.debug("Redis connection closed.")
            except Exception as e:
                log.error(f"Error closing Redis connection: {e}", exc_info=True)
        else:
            log.warning("No Redis client to close.")

    # Example usage (for testing or direct instantiation outside lifespan):
    # async def main():
    #     cache = RedisCacheService(redis_url="redis://localhost:6379/0")
    #     await cache.write("mykey", {"data": "myvalue"}, ttl=60)
    #     retrieved = await cache.read("mykey")
    #     print(f"Retrieved: {retrieved}")
    #     await cache.close()