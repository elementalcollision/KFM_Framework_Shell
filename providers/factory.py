"""Provider factory for instantiating adapters."""

import logging
from typing import Dict, Optional, Type

# Local application imports
from core.config import AppConfig, OpenAIProviderConfig, AnthropicProviderConfig, GroqProviderConfig # Import the main config model and provider configs
from providers.base import ProviderInterface       # Import the base interface
from providers.openai import OpenAIAdapter         # Import the specific adapter
# Import other adapters as they are created, e.g.:
from .anthropic import AnthropicAdapter
from .groq import GroqAdapter
from providers.exceptions import ProviderError, ConfigurationError

logger = logging.getLogger(__name__)

class ProviderFactory:
    """
    Factory for creating and managing instances of provider adapters.

    Ensures that adapters are instantiated with the correct configuration
    (including loaded secrets) and provides a simple caching mechanism
    to reuse adapter instances.
    """
    def __init__(self, config: AppConfig):
        """
        Initializes the factory with application configuration.

        Args:
            config: The loaded AppConfig object.
        """
        if not config or not config.providers:
            raise ConfigurationError("Providers configuration is missing or invalid.")
        self.config: AppConfig = config
        self._adapter_cache: Dict[str, ProviderInterface] = {}
        self._adapter_map: Dict[str, Type[ProviderInterface]] = {
            "openai": OpenAIAdapter,
            "anthropic": AnthropicAdapter,
            "groq": GroqAdapter,
        }

    def get_adapter(self, provider_name: str) -> ProviderInterface:
        """
        Gets an initialized provider adapter instance by name.

        Args:
            provider_name: The name of the provider (e.g., "openai").

        Returns:
            An instance of the requested ProviderInterface implementation.

        Raises:
            ConfigurationError: If the requested provider is not configured
                              or if its configuration is invalid (e.g., missing API key).
            ProviderError: If the requested provider name is unknown/unsupported.
        """
        provider_name = provider_name.lower() # Normalize name

        # Return cached instance if available
        if provider_name in self._adapter_cache:
            logger.debug(f"Returning cached adapter instance for provider: {provider_name}")
            return self._adapter_cache[provider_name]

        # Check if provider is supported
        adapter_class = self._adapter_map.get(provider_name)
        if not adapter_class:
            logger.error(f"Attempted to get adapter for unsupported provider: {provider_name}")
            raise ProviderError(f"Unsupported provider: {provider_name}")

        # Get the specific configuration section for this provider
        # and ensure it's the correct Pydantic model type
        provider_config_instance: Optional[OpenAIProviderConfig | AnthropicProviderConfig | GroqProviderConfig] = None
        expected_config_type: Optional[Type[OpenAIProviderConfig | AnthropicProviderConfig | GroqProviderConfig]] = None

        if provider_name == "openai":
            provider_config_instance = self.config.providers.openai
            expected_config_type = OpenAIProviderConfig
        elif provider_name == "anthropic":
            provider_config_instance = self.config.providers.anthropic
            expected_config_type = AnthropicProviderConfig
        elif provider_name == "groq":
            provider_config_instance = self.config.providers.groq
            expected_config_type = GroqProviderConfig
        # Add elif for other providers (e.g., groq)
        
        if not provider_config_instance:
            logger.error(f"Configuration section for provider '{provider_name}' not found in config.toml.")
            raise ConfigurationError(f"Provider '{provider_name}' is not configured.")
        
        if expected_config_type and not isinstance(provider_config_instance, expected_config_type):
            # This should ideally be caught by Pydantic validation during config load
            logger.error(f"Configuration for provider '{provider_name}' is of unexpected type. Expected {expected_config_type}, got {type(provider_config_instance)}.\n")
            raise ConfigurationError(f"Invalid configuration type for provider '{provider_name}'.")

        # Extract the loaded API key (which should be in the private '_api_key' field)
        api_key = getattr(provider_config_instance, '_api_key', None)
        if not api_key:
            # This should have been caught by ConfigLoader, but double-check
            env_var_name = getattr(provider_config_instance, 'api_key_env_var', 'N/A')
            logger.error(f"API key for provider '{provider_name}' was not loaded. Expected env var: {env_var_name}")
            raise ConfigurationError(f"API key for provider '{provider_name}' is missing. Ensure env var '{env_var_name}' is set.")

        # Instantiate the adapter
        try:
            logger.info(f"Instantiating adapter for provider: {provider_name}")
            # Pass the loaded API key and the specific config section
            adapter_instance = adapter_class(api_key=api_key, config=provider_config_instance) # type: ignore
            self._adapter_cache[provider_name] = adapter_instance
            logger.info(f"Successfully instantiated adapter for provider: {provider_name}")
            return adapter_instance
        except Exception as e:
            logger.exception(f"Failed to instantiate adapter for provider '{provider_name}': {e}")
            # Catch specific instantiation errors if needed
            raise ProviderError(f"Failed to create adapter instance for '{provider_name}': {e}") from e

    async def close_all(self) -> None:
        """Closes all cached provider adapter instances that have a close method."""
        logger.info("Closing all cached provider adapters...")
        for provider_name, adapter_instance in self._adapter_cache.items():
            if hasattr(adapter_instance, 'close') and callable(adapter_instance.close):
                try:
                    logger.debug(f"Closing adapter for provider: {provider_name}")
                    await adapter_instance.close() # type: ignore
                    logger.info(f"Successfully closed adapter for provider: {provider_name}")
                except Exception as e:
                    logger.exception(f"Failed to close adapter for provider '{provider_name}': {e}")
            else:
                logger.debug(f"Adapter for provider '{provider_name}' does not have a close method.")
        self._adapter_cache.clear() # Clear cache after closing
        logger.info("All cached provider adapters processed for closure.")

# Example Usage (requires a loaded AppConfig object):
# Assume 'app_config' is an instance of AppConfig from ConfigLoader
# factory = ProviderFactory(app_config)
# openai_adapter = factory.get_adapter("openai")
# response = await openai_adapter.generate("Hello world", model_config={"model": "gpt-4o"}) 