"""Configuration loading (ConfigLoader)."""

import os
import toml
from typing import Dict, Any, Optional, Union, List
from pydantic import BaseModel, Field, ValidationError, SecretStr, validator, HttpUrl, DirectoryPath, FilePath, AliasChoices, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
import re

# from .models import ModelPricing # Remove this incorrect import

# Configure logging early, before any potential issues during config load
# Although structlog is preferred, use standard logging for config phase issues
# to avoid circular dependencies or config-dependent logger setup.
try:
    from .logging_config import configure_logging
    # Basic config for potential config loading issues
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper()) 
except ImportError:
    # Fallback if logging_config is not available yet
    logging.basicConfig(level="INFO") 
    logging.getLogger(__name__).warning("core.logging_config not found, using basic logging.")

config_logger = logging.getLogger(__name__)

# --- Pydantic Models for Config Structure ---

# NEW: LLMConfig for detailed LLM settings
class LLMConfig(BaseModel):
    model: Optional[str] = Field(None, description="The specific model name to be used for LLM tasks (e.g., 'gpt-4o', 'claude-3-opus-20240229').")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary model parameters (e.g., temperature, max_tokens, top_p).")
    stream: bool = Field(False, description="Whether to stream responses for LLM tasks.")

# NEW: EmbeddingConfig for detailed embedding settings
class EmbeddingConfig(BaseModel):
    model: Optional[str] = Field(None, description="The specific model name to be used for embedding tasks (e.g., 'text-embedding-ada-002').")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary embedding model parameters (e.g., normalize_embeddings).")
    # provider_id: Optional[str] = Field(None, description="Optional: Specific provider for this embedding config, if different from parent.") # Consider if needed later

# Based on examples in architecture_document.md

# Moved from core/personality.py to break circular import
class ToolDefinition(BaseModel):
    """Defines a tool available within a personality."""
    name: str = Field(..., description="Unique name of the tool (e.g., 'web_search', 'database_query').")
    description: str = Field(..., description="Description of what the tool does, used for planning.")
    # Parameters schema could be added later (e.g., using JSON Schema)

class PlanningConfig(BaseModel):
    """Configuration specific to the planning phase for this personality."""
    provider: Optional[str] = Field(None, description="Preferred provider for planning (overrides core default).")
    model: Optional[str] = Field(None, description="Preferred model for planning (overrides core default).")
    prompt_strategy: Optional[str] = Field(None, description="Specific prompt strategy for planning (e.g., 'react', 'simple').") # Future use
    instructions: Optional[str] = Field(None, description="Additional instructions for the planner LLM.")

class ResponseConfig(BaseModel):
    """Configuration specific to the final response generation phase."""
    provider: Optional[str] = Field(None, description="Preferred provider for response generation (overrides core default).")
    model: Optional[str] = Field(None, description="Preferred model for response generation (overrides core default).")
    instructions: Optional[str] = Field(None, description="Additional instructions for the response LLM.")
    # Example: persona reinforcement

class MemoryConfigPersonality(BaseModel):
    """Configuration related to memory usage for this personality."""
    history_window: Optional[int] = Field(None, description="Number of past turns to consider.")
    allow_long_term_storage: bool = Field(True, description="Whether this personality can store long-term memories.")
    # Add other memory-related settings (e.g., summarization strategy)

class PersonalityConfig(BaseModel):
    """Configuration loaded from a personality pack file."""
    id: str = Field(..., description="Unique identifier for the personality (e.g., 'helpful_assistant'). Should match filename stem.")
    name: str = Field(..., description="User-facing display name.")
    description: str = Field(..., description="Short description of the personality's role or function.")
    system_prompt_file: Optional[str] = Field(None, description="Relative path to a file containing the system prompt (e.g., 'prompts/system.md').")
    _system_prompt_content: Optional[str] = PrivateAttr(default=None)
    
    # NEW fields for provider and model configuration, aligning with StepProcessor
    provider_id: Optional[str] = Field(None, description="Default provider ID for this personality (e.g., 'openai_chat'). Overrides AppConfig default.")
    llm: Optional[LLMConfig] = Field(default_factory=LLMConfig, description="LLM configuration for generation tasks. Overrides provider defaults.")
    embedding: Optional[EmbeddingConfig] = Field(default_factory=EmbeddingConfig, description="Embedding configuration. Overrides provider defaults.")

    # Existing granular configs - review if StepProcessor should use these or the new top-level ones.
    # For now, StepProcessor uses personality.provider_id and personality.llm directly.
    planning: PlanningConfig = Field(default_factory=PlanningConfig, description="Planning-specific configuration.")
    response: ResponseConfig = Field(default_factory=ResponseConfig, description="Response generation configuration.")
    memory: MemoryConfigPersonality = Field(default_factory=MemoryConfigPersonality, description="Memory configuration.") 
    tools: List[ToolDefinition] = Field(default_factory=list, description="List of tools available to this personality.")

    @property
    def system_prompt(self) -> Optional[str]:
        """Returns the loaded system prompt content."""
        return self._system_prompt_content

    @validator('id')
    def id_must_be_valid_filename(cls, v):
        invalid_chars = ' /\\:*?"<>|' 
        if any(c in v for c in invalid_chars):
            raise ValueError(f"Personality ID '{v}' contains invalid characters.")
        return v
# End moved section from core/personality.py

class CoreRuntimeFeatureFlags(BaseModel):
    enable_parallel_step_execution: bool = False

class CoreRuntimeConfig(BaseModel):
    max_turn_duration_seconds: int = 120
    max_steps_per_plan: int = 25
    default_provider: str = Field("openai_chat", description="Default provider ID for LLM generation tasks if not specified elsewhere.")
    default_embedding_provider: Optional[str] = Field(None, description="Default provider ID for embedding tasks if not specified elsewhere.")
    max_plan_generation_retries: int = 2
    max_step_execution_retries: int = 3
    default_personality_id: str = "default_assistant_v1.0"
    default_personality_version: str = "latest"
    max_conversation_history_turns: int = 20
    max_context_tokens_for_llm: int = 8000
    feature_flags: CoreRuntimeFeatureFlags = Field(default_factory=CoreRuntimeFeatureFlags)

class ProviderConfig(BaseModel):
    # Common fields for all providers, specific ones might be added in subclasses if needed
    api_key_env_var: Optional[str] = None
    _api_key: Optional[str] = PrivateAttr(default=None) # Loaded from env var, use PrivateAttr

    llm: Optional[LLMConfig] = Field(default=None, description="Configuration for LLM generation tasks with this provider.")
    embedding: Optional[EmbeddingConfig] = Field(default=None, description="Configuration for embedding tasks with this provider.")

# --- Model Pricing Structure ---
class ModelPricing(BaseModel):
    """Stores cost per million tokens for a specific model."""
    prompt_token_cost_usd_million: Optional[float] = Field(None, description="Cost per 1 million prompt tokens in USD.")
    completion_token_cost_usd_million: Optional[float] = Field(None, description="Cost per 1 million completion tokens in USD.")
    embedding_token_cost_usd_million: Optional[float] = Field(None, description="Cost per 1 million total tokens for embedding models in USD.")
    # Add other cost types if needed (e.g., image generation cost)

class OpenAIProviderConfig(ProviderConfig): 
    # default_model: str = "gpt-4o" # Removed, use llm.model
    connection_pool_size: int = 20
    model_pricing: Dict[str, ModelPricing] = Field(default_factory=dict, description="Pricing information keyed by model name.")
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig(model="gpt-4o")) # Default OpenAI LLM config
    embedding: EmbeddingConfig = Field(default_factory=lambda: EmbeddingConfig(model="text-embedding-ada-002")) # Default OpenAI Embedding

class AnthropicProviderConfig(ProviderConfig): 
    # default_model: str = "claude-3-opus-20240229" # Removed
    connection_pool_size: int = 10 
    model_pricing: Dict[str, ModelPricing] = Field(default_factory=dict, description="Pricing information keyed by model name (e.g., claude-3-opus-20240229).")
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig(model="claude-3-opus-20240229"))
    # Anthropic does not have native embeddings per research; leave embedding as None by default
    embedding: Optional[EmbeddingConfig] = None 

class GroqProviderConfig(ProviderConfig):
    # default_model: str = "llama3-8b-8192" # Removed
    model_pricing: Dict[str, ModelPricing] = Field(
        default_factory=dict,
        description="Pricing per million tokens. Needs external update based on actual Groq pricing."
    )
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig(model="llama3-8b-8192"))
    # Groq has embeddings. Placeholder model name, verify from Groq docs.
    embedding: EmbeddingConfig = Field(default_factory=lambda: EmbeddingConfig(model="text-embedding-groq-placeholder")) 

class ProvidersConfig(BaseModel):
    openai: Optional[OpenAIProviderConfig] = None
    anthropic: Optional[AnthropicProviderConfig] = None
    groq: Optional[GroqProviderConfig] = None # Add Groq config section
    # Add other providers here as needed (groq, etc.)

class MemoryVectorStoreConfig(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    password_env_var: Optional[str] = None
    database: Optional[str] = None
    _password: Optional[str] = None # Loaded from env var

class MemoryCacheConfig(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    password_env_var: Optional[str] = None
    db: Optional[int] = None
    _password: Optional[str] = None # Loaded from env var

class RedisConfig(BaseSettings):
    # Allow overriding via REDIS_URL env var
    url: str = Field("redis://localhost:6379/0", validation_alias=AliasChoices("url", "REDIS_URL"))

# NEW LanceDB Config
class LanceDBConfig(BaseModel):
    uri: str = Field("./data/lancedb_store", description="Path or URI for the LanceDB database.")
    table_name: str = Field("agent_memory", description="Default table name for agent memory.")
    # embedding_provider_id: str = Field("openai", description="ID of the provider to use for embeddings for LanceDB.")
    # We will likely pass the embedding provider instance directly during initialization
    embedding_function_name: Optional[str] = None
    embedding_model_name: Optional[str] = None
    # mode: str = "overwrite" # If needed for table creation

class MemoryConfig(BaseModel):
    # Flags to enable/disable memory components
    redis_enabled: bool = True
    vector_store_enabled: bool = True
    
    # Cache config (relevant if redis_enabled is True)
    cache_ttl_seconds: int = 3600 # Default TTL for cache entries (1 hour)

    # Vector Store Config (relevant if vector_store_enabled is True)
    # Simplify to a single optional LanceDB config for now
    lancedb: Optional[LanceDBConfig] = None 

    default_embedding_provider_id: str = 'openai' # TODO: Link this better? Or remove?

class IggyStreamDefaults(BaseModel):
    partitions: Optional[int] = None
    retention_policy: Optional[str] = None

class IggyIntegrationConfig(BaseModel):
    address: str = "localhost"
    tcp_port: int = 8090
    quic_port: int = 8070
    http_port: int = 3000
    default_transport: str = "tcp"
    username: Optional[str] = None
    password_env_var: Optional[str] = None
    _password: Optional[str] = None # Loaded from env var
    tls_enabled: bool = False
    # Add other Iggy fields (TLS paths, clustering, schema registry etc.)
    stream_defaults: Dict[str, IggyStreamDefaults] = Field(default_factory=dict)

class PersonalitiesConfig(BaseModel):
    directory: str = Field("./personalities", description="Directory where personality pack YAML files are stored.")
    default_personality_id: Optional[str] = Field(None, description="ID of the default personality to use if none is specified.")

class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_nested_delimiter='__',
        toml_file='config.toml',
        extra='ignore' # Ignore extra fields from files/env
    )

    # Top-level settings
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_json: bool = Field(default=False, validation_alias="LOG_JSON") # Set to true for JSON logs
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False # Set True for Uvicorn auto-reload (dev only)

    # Provider configurations (can be nested in TOML)
    providers: Dict[str, Union[OpenAIProviderConfig, AnthropicProviderConfig, GroqProviderConfig]] = Field(default_factory=dict)

    # Memory configuration
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    # Conditionally include Redis config only if cache is enabled
    redis: Optional[RedisConfig] = None

    # Personality configuration
    personality: PersonalitiesConfig = Field(default_factory=PersonalitiesConfig)

    # Internal queue settings (optional)
    event_queue_max_size: int = 1000

    # --- Model Validators ---
    @model_validator(mode='before')
    @classmethod
    def load_provider_configs(cls, values):
        # This allows providers to be defined flatly in env vars like
        # PROVIDERS_OPENAI_API_KEY=... or nested in TOML/JSON.
        # We extract known provider types based on keys.
        providers_data = values.get('providers', {})
        if not isinstance(providers_data, dict):
             config_logger.warning("'providers' config is not a dictionary. Skipping provider loading.")
             return values
             
        # Example: Check for keys indicating specific providers
        # A more robust way might involve explicit type markers in the config.
        if 'openai' in providers_data and isinstance(providers_data['openai'], dict):
            # Assume openai section corresponds to OpenAIProviderConfig
            # Pydantic-settings should handle the prefix mapping correctly later
            pass # No explicit action needed here if structure matches
        if 'anthropic' in providers_data and isinstance(providers_data['anthropic'], dict):
            pass
        if 'groq' in providers_data and isinstance(providers_data['groq'], dict):
            pass
            
        # Add default empty dicts if provider sections are missing, 
        # so pydantic-settings can attempt to load from env vars
        for provider_key in ['openai', 'anthropic', 'groq']:
            if provider_key not in providers_data:
                providers_data[provider_key] = {} # Add empty dict to allow env var loading
        
        values['providers'] = providers_data
        return values

    @model_validator(mode='after')
    def check_redis_config(self):
        # Ensure Redis config is present if memory cache is enabled
        if self.memory and self.memory.redis_enabled and self.redis is None:
            config_logger.warning("Memory cache (Redis) is enabled but Redis is not explicitly configured. Attempting default Redis config.")
            self.redis = RedisConfig() # Use default Redis settings
        elif self.memory and not self.memory.redis_enabled:
            self.redis = None # Explicitly set to None if cache is disabled
        return self

# --- Config Loader Class ---

ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')

class ConfigError(Exception):
    """Custom exception for configuration loading errors."""
    pass

class ConfigLoader:
    def __init__(self, config_path: str = "config.toml"):
        self.config_path = config_path
        self._config: Optional[AppConfig] = None
        self._raw_config: Optional[Dict[str, Any]] = None
        self.load_config()

    def _resolve_env_vars(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively resolve environment variable placeholders."""
        resolved_dict = {}
        for key, value in config_dict.items():
            if isinstance(value, dict):
                resolved_dict[key] = self._resolve_env_vars(value)
            elif isinstance(value, str):
                match = ENV_VAR_PATTERN.fullmatch(value)
                if match:
                    env_var_name = match.group(1)
                    env_var_value = os.environ.get(env_var_name)
                    if env_var_value is None:
                        # Per architecture doc, fail if missing on initial load
                        raise ConfigError(f"Required environment variable '{env_var_name}' referenced in config is not set.")
                    resolved_dict[key] = env_var_value
                    config_logger.debug(f"Resolved '{value}' from environment variable '{env_var_name}'")
                else:
                    resolved_dict[key] = value
            else:
                resolved_dict[key] = value
        return resolved_dict

    def _load_secrets_into_models(self, config_model: AppConfig, raw_config: Dict[str, Any]):
        """Load secrets from *_env_var fields into the Pydantic models."""
        # Example for providers
        if config_model.providers:
            for provider_name, provider_conf in config_model.providers.items():
                if provider_conf and provider_conf.api_key_env_var:
                    key_val = os.environ.get(provider_conf.api_key_env_var)
                    if not key_val:
                         raise ConfigError(f"Environment variable '{provider_conf.api_key_env_var}' for provider '{provider_name}' not set.")
                    provider_conf._api_key = key_val
        
        # Example for memory (add pgvector, redis etc.)
        if config_model.memory and config_model.memory.pgvector and config_model.memory.pgvector.password_env_var:
            pwd_val = os.environ.get(config_model.memory.pgvector.password_env_var)
            if not pwd_val:
                raise ConfigError(f"Environment variable '{config_model.memory.pgvector.password_env_var}' for pgvector password not set.")
            config_model.memory.pgvector._password = pwd_val

        # Example for Iggy
        if config_model.iggy_integration and config_model.iggy_integration.password_env_var:
            pwd_val = os.environ.get(config_model.iggy_integration.password_env_var)
            if not pwd_val:
                 raise ConfigError(f"Environment variable '{config_model.iggy_integration.password_env_var}' for iggy password not set.")
            config_model.iggy_integration._password = pwd_val

        # Add logic for other components needing secrets


    def load_config(self):
        """Loads configuration from the TOML file, resolves env vars, and validates."""
        config_logger.info(f"Loading configuration from: {self.config_path}")
        try:
            with open(self.config_path, 'r') as f:
                raw_config_with_placeholders = toml.load(f)
            
            # Note: The _resolve_env_vars step is good for direct substitution,
            # but the architecture doc implies loading keys via *_env_var fields.
            # We'll keep the env var loading separate for clarity.
            # raw_config_resolved = self._resolve_env_vars(raw_config_with_placeholders)
            self._raw_config = raw_config_with_placeholders

            # Validate structure and types using Pydantic
            self._config = AppConfig.model_validate(self._raw_config)

            # Load secrets specified by *_env_var fields
            self._load_secrets_into_models(self._config, self._raw_config)

            config = self._config
            config_logger.info("Configuration loaded successfully.", 
                             log_level=config.log_level, 
                             log_json=config.log_json,
                             cache_enabled=config.memory.cache_enabled, 
                             vector_store_enabled=config.memory.vector_store_enabled)

        except FileNotFoundError:
            config_logger.error(f"Configuration file not found at {self.config_path}")
            raise ConfigError(f"Config file not found: {self.config_path}")
        except toml.TomlDecodeError as e:
            config_logger.error(f"Error decoding TOML file {self.config_path}: {e}")
            raise ConfigError(f"Invalid TOML format: {e}")
        except ValidationError as e:
            config_logger.error(f"Configuration validation error: {e}")
            raise ConfigError(f"Invalid configuration structure: {e}")
        except ConfigError as e: # Catch specific ConfigErrors (like missing env vars)
             config_logger.error(f"Configuration error: {e}")
             raise # Re-raise the specific ConfigError
        except Exception as e:
            config_logger.error(f"An unexpected error occurred during config loading: {e}", exc_info=True)
            raise ConfigError(f"Unexpected error loading config: {e}")

    def get_config(self) -> AppConfig:
        """Returns the loaded and validated configuration object."""
        if self._config is None:
            # This should ideally not happen if constructor calls load_config
            config_logger.warning("Config accessed before successful loading. Attempting reload.")
            self.load_config()
            if self._config is None: # Still None after reload attempt
                 raise ConfigError("Configuration could not be loaded.")
        return self._config

    # --- Placeholder for Hot-Reloading --- #
    def start_watcher(self):
        # TODO: Implement file system watcher (e.g., using watchdog)
        config_logger.info("Config file watcher started (placeholder).")
        pass

    def stop_watcher(self):
        # TODO: Stop the file system watcher
        config_logger.info("Config file watcher stopped (placeholder).")
        pass

    def _on_config_change(self):
        # TODO: Callback for file change - triggers reload, validation, and notification
        config_logger.info(f"Config file {self.config_path} changed. Reloading (placeholder).")
        try:
            self.load_config()
            # TODO: Notify components of config change (e.g., via event)
        except ConfigError as e:
            config_logger.error(f"Hot-reload failed: {e}. Keeping previous configuration.")
        except Exception as e:
             config_logger.error(f"Unexpected error during hot-reload: {e}. Keeping previous configuration.", exc_info=True)

# Example usage (typically instantiated once and shared/injected)
# config_loader = ConfigLoader()
# app_config = config_loader.get_config()
# print(app_config.core_runtime.default_planning_model)
# print(app_config.providers.openai._api_key) # Access loaded secret 