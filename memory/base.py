from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional, Protocol, runtime_checkable

@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for components that can generate vector embeddings."""
    
    @property
    @abstractmethod
    def embedding_dimension(self) -> int:
        """Returns the dimension of the vectors produced by this provider."""
        ...

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Generate embedding for a single piece of text."""
        ...

    # Optional: Add embed_batch for efficiency later if needed
    # @abstractmethod
    # async def embed_batch(self, texts: List[str]) -> List[List[float]]:
    #     ...

class MemoryService(ABC):
    """Abstract base class for memory service implementations."""

    @abstractmethod
    async def write(self, key: str, value: Any, metadata: Optional[Dict] = None, ttl: Optional[int] = None) -> None:
        """
        Write data to the memory store.

        Args:
            key: The unique identifier for the data.
            value: The data to store.
            metadata: Optional metadata associated with the data.
            ttl: Optional time-to-live in seconds for cache entries.
        """
        pass

    @abstractmethod
    async def search(self, query: str, top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        """
        Search the memory store based on a query.

        Args:
            query: The search query (e.g., text for semantic search).
            top_k: The maximum number of results to return.
            filters: Optional filters to apply to the search.

        Returns:
            A list of search results, typically dictionaries containing the stored value and metadata.
        """
        pass

    @abstractmethod
    async def read(self, key: str) -> Optional[Any]:
        """
        Read data directly by key (primarily for cache-like access).

        Args:
            key: The unique identifier for the data.

        Returns:
            The stored value, or None if the key is not found or expired.
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """
        Delete data by key.

        Args:
            key: The unique identifier for the data to delete.
        """
        pass 