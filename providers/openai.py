"""OpenAI Provider Adapter."""

import logging
import os
from typing import List, Dict, Any, Optional, Tuple
import time

# Third-party imports
import openai # Ensure this is installed via requirements.txt or pyproject.toml
from openai import AsyncOpenAI, AuthenticationError as OpenAIAuthenticationError, RateLimitError as OpenAIRateLimitError, BadRequestError as OpenAIBadRequestError, APIError as OpenAIAPIError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

# Local application imports
from .base import ProviderInterface, LLMResponse, EmbeddingResponse, ModerationResponse
from core.config import OpenAIProviderConfig, ModelPricing # Import specific config model
from .exceptions import ProviderError, AuthenticationError, RateLimitError, CallError, ConfigurationError
from core.models import StepMetrics
from memory.base import EmbeddingProvider
from core.metrics import record_llm_request, record_embedding_request

# Default dimension for text-embedding-ada-002
DEFAULT_OPENAI_EMBEDDING_DIMENSION = 1536

log = structlog.get_logger(__name__)

class OpenAIAdapter(ProviderInterface, EmbeddingProvider):
    """Adapter for interacting with OpenAI APIs."""

    def __init__(self, config: OpenAIProviderConfig):
        """
        Initializes the OpenAI adapter.

        Args:
            config: The OpenAI-specific configuration object.
        """
        self.config = config
        api_key = os.environ.get(config.api_key_env_var) if config.api_key_env_var else None
        if not api_key:
            # Fallback to OPENAI_API_KEY if specific env var is not set or not provided
            api_key = os.environ.get("OPENAI_API_KEY")

        if not api_key:
             raise ConfigurationError(f"OpenAI API key not found in environment variable '{config.api_key_env_var or 'OPENAI_API_KEY'}'")

        try:
            self.aclient = AsyncOpenAI(api_key=api_key)
            log.info("OpenAI Async Client initialized successfully.")
        except Exception as e:
            log.exception("Failed to initialize OpenAI client.")
            raise ConfigurationError(f"Failed to initialize OpenAI client: {e}") from e

    @property
    def embedding_dimension(self) -> int:
        """Returns the dimension of the vectors produced by the default OpenAI embedding model."""
        # TODO: Make this dynamic based on the actual embedding model configured/used?
        # For now, assume text-embedding-ada-002 is implicitly used by embed()
        return DEFAULT_OPENAI_EMBEDDING_DIMENSION

    async def generate(self, prompt: str, model_config: Dict[str, Any], **kwargs) -> LLMResponse:
        """
        Generates text using OpenAI's chat completions endpoint.

        Args:
            prompt: The user prompt or a structured prompt string. 
                    (Note: For chat models, this often represents the latest user message. 
                     Full conversation history needs separate handling, potentially passed via kwargs 
                     or managed by the calling service).
            model_config: Dictionary containing model parameters like 'model', 'temperature', 'max_tokens'.
            **kwargs: Additional context (e.g., 'conversation_history': List[Message]).

        Returns:
            An LLMResponse object.
        """
        model = model_config.get("model", self.config.default_model)
        temperature = model_config.get("temperature") # Let OpenAI SDK handle default if None
        max_tokens = model_config.get("max_tokens")   # Let OpenAI SDK handle default if None

        # Prepare messages - simple prompt for now, can enhance with history from kwargs
        messages = [{"role": "user", "content": prompt}]
        # TODO: Incorporate conversation_history from kwargs if provided

        log.debug(f"Calling OpenAI generate: model={model}, temp={temperature}, max_tokens={max_tokens}")

        # Track request timing and metrics
        start_time = time.time()
        error_type = None
        status = "success"

        try:
            response = await self.aclient.chat.completions.create(
                model=model,
                messages=messages, # type: ignore (Pydantic models should be compatible)
                temperature=temperature,
                max_tokens=max_tokens,
                # Add other parameters like stream=False if needed
            )

            content = response.choices[0].message.content
            usage = response.usage

            cost = 0.0
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            if usage:
                pricing_info = self.config.model_pricing.get(model)
                if pricing_info:
                    prompt_cost_usd = 0.0
                    completion_cost_usd = 0.0
                    if pricing_info.prompt_token_cost_usd_million is not None and prompt_tokens > 0:
                        prompt_cost_usd = (prompt_tokens / 1_000_000) * pricing_info.prompt_token_cost_usd_million
                    if pricing_info.completion_token_cost_usd_million is not None and completion_tokens > 0:
                        completion_cost_usd = (completion_tokens / 1_000_000) * pricing_info.completion_token_cost_usd_million
                    cost = prompt_cost_usd + completion_cost_usd
                    log.debug(f"Calculated cost for {model}: ${cost:.6f} (P: ${prompt_cost_usd:.6f}, C: ${completion_cost_usd:.6f})")
                else:
                    log.warning(f"No pricing information found for model '{model}' in OpenAIProviderConfig. Cost will be reported as 0.")

            end_time = time.time()
            
            # Record metrics
            record_llm_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                cost=cost,
                status=status
            )

            return LLMResponse(
                text_content=content,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost=cost,
                is_error=False
            )

        except OpenAIAuthenticationError as e:
            error_type = "auth"
            status = "error"
            log.error(f"OpenAI authentication error: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_llm_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                output_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise AuthenticationError(f"OpenAI Auth Error: {e}") from e
            
        except OpenAIRateLimitError as e:
            error_type = "rate_limit"
            status = "error"
            log.warning(f"OpenAI rate limit exceeded: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_llm_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                output_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise RateLimitError(f"OpenAI Rate Limit Error: {e}") from e
            
        except OpenAIBadRequestError as e: # Often model not found or invalid params
            error_type = "bad_request"
            status = "error"
            log.error(f"OpenAI bad request error: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_llm_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                output_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise CallError(f"OpenAI Bad Request Error: {e}") from e
            
        except OpenAIAPIError as e: # General API errors (5xx etc)
            error_type = "api"
            status = "error"
            log.error(f"OpenAI API error: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_llm_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                output_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise ProviderError(f"OpenAI API Error: {e}") from e
            
        except Exception as e:
            error_type = "unknown"
            status = "error"
            log.exception("An unexpected error occurred during OpenAI generate call.")
            
            # Record error metrics
            end_time = time.time()
            record_llm_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                output_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise ProviderError(f"Unexpected error in OpenAI generate: {e}") from e

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type(RateLimitError))
    async def embed(self, text_chunks: List[str], model_config: Dict[str, Any], **kwargs) -> EmbeddingResponse:
        """
        Generates embeddings for text chunks using OpenAI.

        Args:
            text_chunks: A list of text strings to embed.
            model_config: Dictionary containing model parameters like 'model'.
            **kwargs: Additional keyword arguments.

        Returns:
            An EmbeddingResponse object.
        """
        model = model_config.get("model", "text-embedding-3-small") # Example default
        dimensions = model_config.get("dimensions") # Optional

        log.debug(f"Calling OpenAI embed: model={model}, chunks={len(text_chunks)}, dimensions={dimensions}")

        # Track request timing and metrics
        start_time = time.time()
        error_type = None
        status = "success"

        try:
            response = await self.aclient.embeddings.create(
                model=model,
                input=text_chunks,
                dimensions=dimensions
            )

            embeddings = [item.embedding for item in response.data]
            usage = response.usage

            cost = 0.0
            input_tokens = usage.prompt_tokens if usage else 0 # OpenAI uses prompt_tokens for embeddings input
            total_tokens_embed = usage.total_tokens if usage else 0

            if usage:
                pricing_info = self.config.model_pricing.get(model)
                if pricing_info and pricing_info.embedding_token_cost_usd_million is not None and total_tokens_embed > 0:
                    cost = (total_tokens_embed / 1_000_000) * pricing_info.embedding_token_cost_usd_million
                    log.debug(f"Calculated cost for embedding model {model}: ${cost:.6f}")
                elif pricing_info and pricing_info.embedding_token_cost_usd_million is None:
                    log.warning(f"Embedding pricing (embedding_token_cost_usd_million) not set for model '{model}' in OpenAIProviderConfig. Cost will be 0.")
                elif not pricing_info:
                    log.warning(f"No pricing information found for embedding model '{model}' in OpenAIProviderConfig. Cost will be 0.")

            end_time = time.time()
            
            # Record metrics
            record_embedding_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=input_tokens,
                cost=cost,
                status=status
            )

            return EmbeddingResponse(
                embeddings=embeddings,
                input_tokens=input_tokens,
                total_tokens=total_tokens_embed,
                cost=cost,
                is_error=False
            )

        except OpenAIAuthenticationError as e:
            error_type = "auth"
            status = "error"
            log.error(f"OpenAI authentication error during embed: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_embedding_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise AuthenticationError(f"OpenAI Auth Error: {e}") from e
            
        except OpenAIRateLimitError as e:
            error_type = "rate_limit"
            status = "error"
            log.warning(f"OpenAI rate limit exceeded during embed: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_embedding_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise RateLimitError(f"OpenAI Rate Limit Error: {e}") from e
            
        except OpenAIBadRequestError as e:
            error_type = "bad_request"
            status = "error"
            log.error(f"OpenAI bad request error during embed: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_embedding_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise CallError(f"OpenAI Bad Request Error: {e}") from e
        except OpenAIAPIError as e:
            error_type = "api"
            status = "error"
            log.error(f"OpenAI API error during embed: {e}")
            
            # Record error metrics
            end_time = time.time()
            record_embedding_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise ProviderError(f"OpenAI API Error: {e}") from e
        except Exception as e:
            error_type = "unknown"
            status = "error"
            log.exception("An unexpected error occurred during OpenAI embed call.")
            
            # Record error metrics
            end_time = time.time()
            record_embedding_request(
                provider="openai",
                model=model,
                start_time=start_time,
                end_time=end_time,
                input_tokens=0,
                cost=0,
                status=status,
                error_type=error_type
            )
            
            raise ProviderError(f"Unexpected error in OpenAI embed: {e}") from e

    async def moderate(self, text: str, model_config: Dict[str, Any], **kwargs) -> ModerationResponse:
        """
        Checks text for harmful content using OpenAI's moderation endpoint.

        Args:
            text: The text string to moderate.
            model_config: Dictionary containing model parameters (usually just 'model').
            **kwargs: Additional keyword arguments.

        Returns:
            A ModerationResponse object.
        """
        # Model is optional for moderation, defaults to text-moderation-latest
        model = model_config.get("model") 

        log.debug(f"Calling OpenAI moderate: model={model or 'default'}")

        try:
            response = await self.aclient.moderations.create(
                input=text,
                model=model
            )

            result = response.results[0]

            # Basic cost - moderation is often free, but check pricing
            cost = 0.0 
            # Example: Check if specific pricing exists for the moderation model
            if model: # Model can be None for moderation
                pricing_info = self.config.model_pricing.get(model)
                if pricing_info:
                    # Assuming a hypothetical cost field for moderation, e.g., per call or per char
                    # For now, let's assume it might use embedding_token_cost_usd_million if text length were relevant
                    # but typically moderation is a fixed low cost or free. Keeping it simple.
                    # if pricing_info.moderation_cost_per_call is not None:
                    #    cost = pricing_info.moderation_cost_per_call
                    log.debug("Pricing info found for moderation model {model}, but no specific cost field implemented yet. Cost remains 0.")
                else:
                    log.debug("No pricing info for moderation model {model}. Cost remains 0.")
            else:
                log.debug("Moderation model not specified. Cost remains 0.")

            return ModerationResponse(
                is_flagged=result.flagged,
                categories=result.categories.model_dump(), # Convert Pydantic model to dict
                scores=result.category_scores.model_dump(), # Convert Pydantic model to dict
                cost=cost, 
                is_error=False
            )
            
        except OpenAIAuthenticationError as e:
            log.error(f"OpenAI authentication error during moderate: {e}")
            raise AuthenticationError(f"OpenAI Auth Error: {e}") from e
        except OpenAIRateLimitError as e:
            log.warning(f"OpenAI rate limit exceeded during moderate: {e}")
            raise RateLimitError(f"OpenAI Rate Limit Error: {e}") from e
        except OpenAIBadRequestError as e:
             log.error(f"OpenAI bad request error during moderate: {e}")
             raise CallError(f"OpenAI Bad Request Error: {e}") from e
        except OpenAIAPIError as e:
            log.error(f"OpenAI API error during moderate: {e}")
            raise ProviderError(f"OpenAI API Error: {e}") from e
        except Exception as e:
            log.exception("An unexpected error occurred during OpenAI moderate call.")
            raise ProviderError(f"Unexpected error in OpenAI moderate: {e}") from e

    async def close(self):
        """Close the OpenAI client connection."""
        if self.aclient:
            try:
                await self.aclient.close()
                log.info("OpenAI async client closed.")
            except Exception as e:
                log.error(f"Error closing OpenAI async client: {e}", exc_info=True)

# Ensure any old class definition like "class Provider(Provider):" is removed.