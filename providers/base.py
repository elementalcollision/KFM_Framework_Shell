"""Base classes and interfaces for provider adapters."""

import abc
from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import AsyncIterable
from core.schema import Step, Message

# Define ProviderInterface (ABC) and common response models (LLMResponse etc.) here

class LLMResponse(BaseModel):
    text_content: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    is_error: bool = False
    error_details: dict | None = None
    # ... other common fields

class EmbeddingResponse(BaseModel): # Added for clarity
    embeddings: list[list[float]]
    input_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    is_error: bool = False
    error_details: dict | None = None

class ModerationResponse(BaseModel): # Added for clarity
    is_flagged: bool
    categories: dict[str, bool] | None = None
    scores: dict[str, float] | None = None
    cost: float | None = None
    is_error: bool = False
    error_details: dict | None = None

class ProviderInterface(abc.ABC):
    @abc.abstractmethod
    async def generate(self, prompt: str, model_config: dict, **kwargs) -> LLMResponse:
        pass

    @abc.abstractmethod
    async def embed(self, text_chunks: list[str], model_config: dict, **kwargs) -> EmbeddingResponse:
        pass

    @abc.abstractmethod
    async def moderate(self, text: str, model_config: dict, **kwargs) -> ModerationResponse:
        pass

class Provider(ABC):
    @abstractmethod
    async def generate(self, step: Step) -> AsyncIterable[Message]: ...