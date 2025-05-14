"""Common exceptions for the Provider Adapter Layer."""

class ProviderError(Exception):
    """Base class for provider-related errors."""
    pass

class AuthenticationError(ProviderError):
    """Error related to provider authentication (e.g., invalid API key)."""
    pass

class RateLimitError(ProviderError):
    """Error indicating a rate limit was exceeded."""
    pass

class ConfigurationError(ProviderError):
    """Error related to provider configuration."""
    pass

class CallError(ProviderError):
    """General error during a provider API call."""
    pass 