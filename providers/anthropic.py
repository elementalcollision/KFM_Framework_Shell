"""Anthropic Provider Adapter."""

import logging
import os
from typing import List, Dict, Any, Optional

# Third-party imports
try:
    import anthropic
    from anthropic import AsyncAnthropic
    from anthropic import APIConnectionError as AnthropicAPIConnectionError
    from anthropic import RateLimitError as AnthropicRateLimitError
    from anthropic import APIStatusError as AnthropicAPIStatusError
    from anthropic import AuthenticationError as AnthropicAuthenticationError
    # Import other specific errors if needed, e.g., BadRequestError
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    # Define dummy types if library is not installed
    class AsyncAnthropic: pass
    class AnthropicAPIConnectionError(Exception): pass
    class AnthropicRateLimitError(Exception): pass
    class AnthropicAPIStatusError(Exception): pass
    class AnthropicAuthenticationError(Exception): pass


# Local application imports
from .base import ProviderInterface, LLMResponse, EmbeddingResponse, ModerationResponse
from core.config import AnthropicProviderConfig # Import specific config model
from .exceptions import ProviderError, AuthenticationError, RateLimitError, CallError, ConfigurationError

# For retry mechanism
import tenacity

import structlog

log = structlog.get_logger(__name__)

class AnthropicAdapter(ProviderInterface):
    """Adapter for interacting with Anthropic APIs."""

    def __init__(self, api_key: str, config: AnthropicProviderConfig):
        """
        Initializes the Anthropic adapter.

        Args:
            api_key: The Anthropic API key.
            config: The Anthropic-specific configuration object.
        """
        if not ANTHROPIC_AVAILABLE:
            raise ConfigurationError("Anthropic SDK not installed. Please install with 'pip install anthropic'.")

        if not api_key:
            raise ConfigurationError("Anthropic API key is required but was not provided.")
        
        try:
            # TODO: Configure client further using config.connection_pool_size etc. if possible
            # The anthropic SDK might use httpx under the hood, check its config options.
            # Default timeout/retries can be set here or handled per-call via Tenacity/with_options
            self.client = AsyncAnthropic(
                api_key=api_key,
                # max_retries=config.max_retries # Example if config added this
                # timeout=config.timeout # Example if config added this
                )
            self.config = config
            log.info("Anthropic Async Client initialized successfully.")
        except Exception as e:
            log.exception("Failed to initialize Anthropic client.")
            raise ConfigurationError(f"Failed to initialize Anthropic client: {e}") from e

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        stop=tenacity.stop_after_attempt(5),
        retry=tenacity.retry_if_exception_type((AnthropicAPIConnectionError, AnthropicRateLimitError)),
        before_sleep=tenacity.before_sleep_log(log, logging.WARNING),
        reraise=True
    )
    async def generate(self, prompt: str, model_config: Dict[str, Any], **kwargs) -> LLMResponse:
        """
        Generates text using Anthropic's messages endpoint.

        Args:
            prompt: The user prompt (often the last message).
            model_config: Dictionary containing model parameters like 'model', 'max_tokens'.
            **kwargs: May include 'system_prompt' (str) and 'conversation_history' (List[Message]).

        Returns:
            An LLMResponse object.
        """
        if not ANTHROPIC_AVAILABLE:
            raise ConfigurationError("Anthropic SDK not installed.")

        model = model_config.get("model", self.config.default_model)
        max_tokens = model_config.get("max_tokens", 1024) # Anthropic requires max_tokens
        temperature = model_config.get("temperature") # Optional
        system_prompt = kwargs.get("system_prompt")
        history: List[Message] = kwargs.get("conversation_history", [])

        # Construct messages list for Anthropic API
        messages_api_format = []
        for msg in history:
            # Ensure role is valid for Anthropic
            if msg.role in ["user", "assistant"]:
                messages_api_format.append({"role": msg.role, "content": msg.content})
            # Ignore system messages in history if system_prompt is provided separately
            elif msg.role == "system" and not system_prompt:
                system_prompt = msg.content # Use the first system message found if no explicit one
        
        # Add the current user prompt
        messages_api_format.append({"role": "user", "content": prompt})

        log.debug(f"Calling Anthropic generate: model={model}, max_tokens={max_tokens}, temp={temperature}")

        try:
            response = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages_api_format, # type: ignore # Pydantic should map well
                system=system_prompt, # Pass system prompt if available
                temperature=temperature,
                # Add other supported parameters from model_config if needed (e.g., top_p, top_k)
            )

            # Extract content (assuming first content block is text)
            # TODO: Handle multiple/different content block types if necessary
            content = ""
            if response.content and isinstance(response.content, list) and len(response.content) > 0:
                first_block = response.content[0]
                if hasattr(first_block, 'text'):
                    content = first_block.text
            
            usage = response.usage
            cost = 0.0
            input_tokens = usage.input_tokens if usage else 0
            output_tokens = usage.output_tokens if usage else 0
            total_tokens = input_tokens + output_tokens # Anthropic usage may not have total_tokens

            if usage:
                pricing_info = self.config.model_pricing.get(model)
                if pricing_info:
                    prompt_cost_usd = 0.0
                    completion_cost_usd = 0.0
                    if pricing_info.prompt_token_cost_usd_million is not None and input_tokens > 0:
                        prompt_cost_usd = (input_tokens / 1_000_000) * pricing_info.prompt_token_cost_usd_million
                    if pricing_info.completion_token_cost_usd_million is not None and output_tokens > 0:
                        completion_cost_usd = (output_tokens / 1_000_000) * pricing_info.completion_token_cost_usd_million
                    cost = prompt_cost_usd + completion_cost_usd
                    log.debug(f"Calculated cost for Anthropic model {model}: ${cost:.6f} (Input: ${prompt_cost_usd:.6f}, Output: ${completion_cost_usd:.6f})")
                else:
                    log.warning(f"No pricing information found for Anthropic model '{model}' in AnthropicProviderConfig. Cost will be 0.")

            return LLMResponse(
                text_content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost=cost,
                is_error=False,
                raw_response=response.model_dump() # Include raw response if needed
            )

        except AnthropicAuthenticationError as e:
            log.error(f"Anthropic authentication error: {e}")
            raise AuthenticationError(f"Anthropic Auth Error: {e.status_code} - {e.body}") from e
        except AnthropicRateLimitError as e:
            log.warning(f"Anthropic rate limit exceeded: {e}")
            # Let Tenacity handle retry, but if it fails eventually, raise RateLimitError
            raise RateLimitError(f"Anthropic Rate Limit Error: {e.status_code} - {e.body}") from e
        # TODO: Map other Anthropic errors (BadRequestError, PermissionError etc.) to CallError
        except AnthropicAPIStatusError as e:
            log.error(f"Anthropic API status error: {e.status_code} - {e.message}")
            # Map potentially recoverable or specific errors?
            # For now, map non-auth/rate-limit status errors to CallError or ProviderError
            if 400 <= e.status_code < 500:
                raise CallError(f"Anthropic API Error (Client): {e.status_code} - {e.message}") from e
            else: # Treat 5xx and others as general provider errors
                raise ProviderError(f"Anthropic API Error (Server/Other): {e.status_code} - {e.message}") from e
        except AnthropicAPIConnectionError as e:
            log.error(f"Anthropic connection error: {e}")
            # Let Tenacity handle retry, but if it fails eventually, raise ProviderError
            raise ProviderError(f"Anthropic Connection Error: {e}") from e
        except Exception as e:
            # Catchall for unexpected errors from the SDK or logic
            log.exception("An unexpected error occurred during Anthropic generate call.")
            raise ProviderError(f"Unexpected error in Anthropic generate: {e}") from e

    async def embed(self, text_chunks: List[str], model_config: Dict[str, Any], **kwargs) -> EmbeddingResponse:
        # Based on current docs review, Anthropic API might not offer a dedicated embedding endpoint via SDK.
        log.warning("Anthropic API does not provide a standard embedding endpoint via the Python SDK.")
        raise NotImplementedError("Anthropic embedding method not available via standard API.")

    async def moderate(self, text: str, model_config: Dict[str, Any], **kwargs) -> ModerationResponse:
        # Based on current docs review, Anthropic API might not offer a moderation endpoint via SDK.
        log.warning("Anthropic API does not provide a standard moderation endpoint via the Python SDK.")
        raise NotImplementedError("Anthropic moderation method not available via standard API.")

    async def close(self) -> None:
        """Closes the underlying AsyncAnthropic client session."""
        if hasattr(self.client, 'aclose') and callable(self.client.aclose):
            try:
                log.info("Closing Anthropic client...")
                await self.client.aclose()
                log.info("Anthropic client closed successfully.")
            except Exception as e:
                log.exception("Failed to close Anthropic client session.")
        else:
            log.warning("AsyncAnthropic client does not have an 'aclose' method. Skipping closure.")