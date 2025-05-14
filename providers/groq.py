"""Groq Provider Adapter."""

import structlog
import logging
import os
from typing import List, Dict, Any, Optional

# Third-party imports
try:
    import groq
    from groq import AsyncGroq
    from groq import APIConnectionError as GroqAPIConnectionError
    from groq import RateLimitError as GroqRateLimitError
    from groq import APIStatusError as GroqAPIStatusError
    from groq import AuthenticationError as GroqAuthenticationError
    # Import other specific errors (e.g., BadRequestError) from groq if needed
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    # Define dummy types if library is not installed
    class AsyncGroq: pass
    class GroqAPIConnectionError(Exception): pass
    class GroqRateLimitError(Exception): pass
    class GroqAPIStatusError(Exception): pass
    class GroqAuthenticationError(Exception): pass

# Local application imports
from .base import ProviderInterface, LLMResponse, EmbeddingResponse, ModerationResponse
from core.config import GroqProviderConfig # Import specific config model
from .exceptions import ProviderError, AuthenticationError, RateLimitError, CallError, ConfigurationError

# For retry mechanism
import tenacity

log = structlog.get_logger(__name__)

class GroqAdapter(ProviderInterface):
    """Adapter for interacting with Groq APIs."""

    def __init__(self, api_key: str, config: GroqProviderConfig):
        """
        Initializes the Groq adapter.

        Args:
            api_key: The Groq API key.
            config: The Groq-specific configuration object.
        """
        if not GROQ_AVAILABLE:
            raise ConfigurationError("Groq SDK not installed. Please install with 'pip install groq'.")

        if not api_key:
            raise ConfigurationError("Groq API key is required but was not provided.")
        
        try:
            # TODO: Configure client further using config if needed (e.g., custom httpx client)
            # Default timeout/retries can be set here or handled per-call via Tenacity/with_options
            self.client = AsyncGroq(
                api_key=api_key,
                # max_retries=config.max_retries # Example if config added this
                # timeout=config.timeout # Example if config added this
            )
            self.config = config
            log.info("Groq Async Client initialized successfully.")
        except Exception as e:
            log.exception("Failed to initialize Groq client.")
            raise ConfigurationError(f"Failed to initialize Groq client: {e}") from e

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        stop=tenacity.stop_after_attempt(5), # SDK default is 2, but let's use 5 like others
        retry=tenacity.retry_if_exception_type((GroqAPIConnectionError, GroqRateLimitError)), # Retry on connection/rate limit errors
        before_sleep=tenacity.before_sleep_log(log, logging.WARNING),
        reraise=True
    )
    async def generate(self, prompt: str, model_config: Dict[str, Any], **kwargs) -> LLMResponse:
        """
        Generates text using Groq's chat completions endpoint.

        Args:
            prompt: The user prompt (often the last message).
            model_config: Dictionary containing model parameters like 'model', 'max_tokens'.
            **kwargs: May include 'system_prompt' (str) and 'conversation_history' (List[Message]).

        Returns:
            An LLMResponse object.
        """
        if not GROQ_AVAILABLE:
            raise ConfigurationError("Groq SDK not installed.")

        model = model_config.get("model", self.config.default_model)
        max_tokens = model_config.get("max_tokens") # Optional for Groq?
        temperature = model_config.get("temperature")
        # TODO: Add other OpenAI-compatible params like top_p, presence_penalty etc.
        system_prompt = kwargs.get("system_prompt")
        history: List[Message] = kwargs.get("conversation_history", [])

        # Construct messages list (OpenAI format)
        messages_api_format = []
        if system_prompt:
            messages_api_format.append({"role": "system", "content": system_prompt})
        for msg in history:
            # Ensure role is valid (user/assistant)
            if msg.role in ["user", "assistant"]:
                messages_api_format.append({"role": msg.role, "content": msg.content})
            elif msg.role == "system" and not system_prompt:
                # Add first system message from history if no separate system_prompt given
                messages_api_format.insert(0, {"role": "system", "content": msg.content})
                system_prompt = msg.content # Avoid adding it twice

        # Add the current user prompt
        messages_api_format.append({"role": "user", "content": prompt})

        log.debug(f"Calling Groq generate: model={model}, max_tokens={max_tokens}, temp={temperature}")

        try:
            # Use Groq client, API is OpenAI compatible
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages_api_format, # type: ignore
                max_tokens=max_tokens,
                temperature=temperature,
                # stream=False, # Assuming non-streaming for now
                # Add other parameters as needed
            )

            content = response.choices[0].message.content
            usage = response.usage

            cost = 0.0
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            if usage:
                # Calculate cost using configured pricing (may be empty/needs update)
                pricing_info = self.config.model_pricing.get(model)
                if pricing_info:
                    prompt_cost_usd = 0.0
                    completion_cost_usd = 0.0
                    if pricing_info.prompt_token_cost_usd_million is not None and prompt_tokens > 0:
                        prompt_cost_usd = (prompt_tokens / 1_000_000) * pricing_info.prompt_token_cost_usd_million
                    if pricing_info.completion_token_cost_usd_million is not None and completion_tokens > 0:
                        completion_cost_usd = (completion_tokens / 1_000_000) * pricing_info.completion_token_cost_usd_million
                    cost = prompt_cost_usd + completion_cost_usd
                    log.debug(f"Calculated cost for Groq model {model}: ${cost:.6f} (Input: ${prompt_cost_usd:.6f}, Output: ${completion_cost_usd:.6f})")
                else:
                    log.warning(f"No pricing information found for Groq model '{model}' in GroqProviderConfig. Cost will be 0.")
            
            # TODO: Extract timing info if needed (usage.prompt_time, usage.completion_time)

            return LLMResponse(
                text_content=content,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost=cost,
                is_error=False,
                raw_response=response.model_dump() # Include raw response
            )

        except GroqAuthenticationError as e:
            log.error(f"Groq authentication error: {e}")
            raise AuthenticationError(f"Groq Auth Error: {e.status_code} - {e.body}") from e
        except GroqRateLimitError as e:
            log.warning(f"Groq rate limit exceeded: {e}")
            # Let Tenacity handle retry
            raise RateLimitError(f"Groq Rate Limit Error: {e.status_code} - {e.body}") from e
        # TODO: Map other Groq errors (BadRequestError etc.) to CallError
        except GroqAPIStatusError as e:
            log.error(f"Groq API status error: {e.status_code} - {e.message}")
            if 400 <= e.status_code < 500:
                 raise CallError(f"Groq API Error (Client): {e.status_code} - {e.message}") from e
            else: # Treat 5xx and others as general provider errors
                 raise ProviderError(f"Groq API Error (Server/Other): {e.status_code} - {e.message}") from e
        except GroqAPIConnectionError as e:
             log.error(f"Groq connection error: {e}")
             # Let Tenacity handle retry
             raise ProviderError(f"Groq Connection Error: {e}") from e
        except Exception as e:
            log.exception("An unexpected error occurred during Groq generate call.")
            raise ProviderError(f"Unexpected error in Groq generate: {e}") from e

    async def embed(self, text_chunks: List[str], model_config: Dict[str, Any], **kwargs) -> EmbeddingResponse:
        # Groq API (based on docs review) focuses on chat completions, no clear embedding endpoint.
        log.warning("Groq API does not provide a standard embedding endpoint via the Python SDK.")
        raise NotImplementedError("Groq embedding method not available via standard API.")

    async def moderate(self, text: str, model_config: Dict[str, Any], **kwargs) -> ModerationResponse:
        # Groq API (based on docs review) focuses on chat completions, no clear moderation endpoint.
        log.warning("Groq API does not provide a standard moderation endpoint via the Python SDK.")
        raise NotImplementedError("Groq moderation method not available via standard API.")

    async def close(self) -> None:
        """Closes the underlying AsyncGroq client session."""
        if hasattr(self.client, 'aclose') and callable(self.client.aclose):
            try:
                log.info("Closing Groq client...")
                await self.client.aclose()
                log.info("Groq client closed successfully.")
            except Exception as e:
                log.exception("Failed to close Groq client session.")
        else:
            log.warning("AsyncGroq client does not have an 'aclose' method. Skipping closure.") 