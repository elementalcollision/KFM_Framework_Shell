class AgentShellError(Exception):
    """Base for all custom exceptions."""

class ProviderNotFound(AgentShellError):
    def __init__(self, name: str):
        super().__init__(f"Provider '{name}' not registered")

class ProviderError(AgentShellError):
    def __init__(self, provider: str, exc: Exception):
        super().__init__(f"{provider} raised {exc!r}")

class ConfigurationError(AgentShellError):
    """Indicates an error in the application's configuration."""
    pass

class ToolNotFoundError(AgentShellError):
    def __init__(self, tool_name: str, personality_id: str):
        super().__init__(f"Tool '{tool_name}' not found in personality '{personality_id}'.")

class ToolExecutionError(AgentShellError):
    def __init__(self, tool_name: str, personality_id: str, original_error: Exception):
        super().__init__(f"Error executing tool '{tool_name}' in personality '{personality_id}'. Original error: {original_error!r}")
        self.original_error = original_error