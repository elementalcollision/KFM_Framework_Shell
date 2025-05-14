from __future__ import annotations
import logging
import yaml
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, validator, ValidationError, PrivateAttr
import asyncio # Added asyncio for execute_tool simulation

# Moved PersonalityConfig and related models to core/config.py
# from .config import AppConfig # Removed import
from .config import PersonalityConfig, PersonalitiesConfig # Import the config models needed

logger = logging.getLogger(__name__)

# Removed ToolDefinition class
# Removed PlanningConfig class
# Removed ResponseConfig class
# Removed MemoryConfig class (the one specific to personality)
# Removed PersonalityConfig class

# --- Personality Pack Manager ---

class PersonalityPackManager:
    """Loads, validates, and provides access to personality configurations."""
    
    def __init__(self, config: PersonalitiesConfig):
        """Initializes the manager and loads personality packs.

        Args:
            config: The PersonalitiesConfig section from the main AppConfig.
        """
        self._personalities: Dict[str, PersonalityConfig] = {}
        self.config = config # Store the PersonalitiesConfig section
        
        if not self.config or not self.config.directory:
            logger.error("Personalities configuration (directory) not found or invalid. Cannot load personality packs.")
            self.directory = None
            return # Stop initialization if config is missing
            
        self.directory = Path(self.config.directory)
        self._load_packs()

    def _load_packs(self):
        """Scans the personality directory, loads and validates YAML files."""
        if not self.directory or not self.directory.is_dir():
            logger.error(f"Personality directory not found or not a directory: {self.directory}")
            return

        logger.info(f"Loading personality packs from: {self.directory}")
        loaded_count = 0
        for filepath in self.directory.glob('*.yaml'): # Or use .yml or .toml
            personality_id_from_filename = filepath.stem
            try:
                with open(filepath, 'r') as f:
                    raw_config = yaml.safe_load(f)
                
                if not isinstance(raw_config, dict):
                    logger.warning(f"Skipping invalid YAML file (not a dictionary): {filepath.name}")
                    continue

                # Ensure the 'id' field matches the filename stem
                if raw_config.get('id') != personality_id_from_filename:
                     logger.warning(f"Personality ID '{raw_config.get('id')}' in {filepath.name} does not match filename stem '{personality_id_from_filename}'. Skipping.")
                     continue

                # Validate using Pydantic model (now imported from core.config)
                config = PersonalityConfig(**raw_config)
                
                # Load prompt content from file if specified
                if config.system_prompt_file:
                    # Base directory comes from self.directory (derived from PersonalitiesConfig)
                    prompt_file_path = self.directory / config.id / config.system_prompt_file
                    try:
                        if not prompt_file_path.is_file():
                            raise FileNotFoundError(f"Prompt file not found at {prompt_file_path}")
                        with open(prompt_file_path, 'r', encoding='utf-8') as pf:
                            config._system_prompt_content = pf.read()
                        logger.debug(f"Loaded system prompt for '{config.id}' from {config.system_prompt_file}")
                    except FileNotFoundError:
                        logger.error(f"System prompt file '{config.system_prompt_file}' specified for personality '{config.id}' but not found at expected path: {prompt_file_path}. Skipping prompt load.")
                    except Exception as prompt_e:
                        logger.exception(f"Error reading system prompt file {prompt_file_path} for personality '{config.id}'. Skipping prompt load.")
                elif 'system_prompt' in raw_config:
                    logger.warning(f"Personality '{config.id}' uses deprecated 'system_prompt' directly in YAML. Please use 'system_prompt_file' instead.")

                self._personalities[config.id] = config
                loaded_count += 1
                logger.debug(f"Successfully loaded and validated personality: {config.id}")

            except yaml.YAMLError as e:
                logger.warning(f"Skipping invalid YAML file {filepath.name}: {e}")
            except ValidationError as e:
                logger.warning(f"Skipping invalid personality configuration in {filepath.name}:\n{e}")
            except Exception as e:
                logger.exception(f"Unexpected error loading personality file {filepath.name}")
        
        logger.info(f"Loaded {loaded_count} personality packs.")
        # Use the stored PersonalitiesConfig
        default_personality_id = self.config.default_personality_id 
        if not self._personalities and default_personality_id:
             logger.warning(f"No personalities loaded, but a default ID '{default_personality_id}' is set in config.")
        elif not self._personalities:
             logger.warning("No personality packs loaded.")


    def get_personality(self, personality_id: str) -> Optional[PersonalityConfig]:
        """Retrieves the configuration for a specific personality.

        Args:
            personality_id: The unique ID of the personality.

        Returns:
            The PersonalityConfig object, or None if not found.
        """
        config = self._personalities.get(personality_id)
        if not config:
            logger.warning(f"Personality ID '{personality_id}' not found.")
            # Use the stored PersonalitiesConfig
            default_id = self.config.default_personality_id 
            if default_id and default_id != personality_id:
                logger.info(f"Falling back to default personality: '{default_id}'")
                return self._personalities.get(default_id)
        return config

    def list_personalities(self) -> List[Dict[str, str]]:
        """Returns a list of available personalities (ID and Name)."""
        return [
            {"id": pid, "name": pconf.name} 
            for pid, pconf in self._personalities.items()
        ]

    def reload_packs(self):
        """Clears the current personality cache and reloads all packs from the directory."""
        logger.info("Reloading personality packs...")
        self._personalities.clear() # Clear the existing cache
        self._load_packs() # Reload from disk
        logger.info(f"Personality packs reloaded. Found {len(self._personalities)} packs.")

    async def execute_tool(self, personality_id: str, tool_name: str, arguments: Dict, context: Any) -> Any: 
        # Changed context type hint to Any temporarily to avoid circular import if ContextManager needed
        """Finds the tool definition, dynamically loads its implementation from personality's tools.py, and executes it."""
        
        personality = self.get_personality(personality_id)
        if not personality:
             raise ValueError(f"Personality '{personality_id}' not found for tool execution.")

        tool_def = next((t for t in personality.tools if t.name == tool_name), None)

        if not tool_def:
             logger.error(f"Tool '{tool_name}' not defined in personality '{personality_id}'.")
             raise ValueError(f"Tool '{tool_name}' not available for this personality.")
             
        logger.info(f"Attempting to execute tool '{tool_name}' for personality '{personality_id}' with args: {arguments}")
        
        # --- Dynamic Tool Execution Logic ---
        tool_result = None
        error_message = None
        try:
            tools_module_path_str = str(self.directory / personality_id / "tools.py")
            tools_module_path = Path(tools_module_path_str)

            if not tools_module_path.is_file():
                raise FileNotFoundError(f"tools.py not found for personality '{personality_id}' at {tools_module_path_str}")

            # Dynamically import the module
            # We need a unique module name to avoid conflicts if multiple tools.py exist
            module_name = f"kfm_fwork.personalities.{personality_id}.tools"
            
            # Use importlib for dynamic loading
            import importlib.util
            spec = importlib.util.spec_from_file_location(module_name, tools_module_path_str)
            if spec is None or spec.loader is None:
                 raise ImportError(f"Could not create module spec for {tools_module_path_str}")
            
            tools_module = importlib.util.module_from_spec(spec)
            # Add to sys.modules *before* exec_module to handle imports within tools.py
            import sys
            sys.modules[module_name] = tools_module
            spec.loader.exec_module(tools_module)

            # Get the function corresponding to the tool name
            tool_function = getattr(tools_module, tool_name, None)

            if not callable(tool_function):
                raise AttributeError(f"Tool function '{tool_name}' not found or not callable in {tools_module_path_str}")

            # Execute the tool function
            # Decide if context should be passed. For now, pass arguments only.
            # Needs careful consideration of security and what context tools need.
            if asyncio.iscoroutinefunction(tool_function):
                tool_result = await tool_function(**arguments)
            else:
                # Allow sync functions for simplicity, but run in executor?
                # For now, run directly. Might block event loop.
                # Consider using asyncio.to_thread for sync tools later.
                tool_result = tool_function(**arguments) 
            
            logger.info(f"Tool '{tool_name}' executed successfully for '{personality_id}'.")
            # TODO: Consider result validation/serialization?

        except FileNotFoundError as e:
             error_message = f"Tool execution failed: {e}"
             logger.error(error_message)
        except ImportError as e:
             error_message = f"Tool execution failed: Could not import tools module or dependencies for '{personality_id}'. Error: {e}"
             logger.error(error_message)
        except AttributeError as e:
            error_message = f"Tool execution failed: {e}"
            logger.error(error_message)
        except Exception as e:
            # Catch errors during the tool function's execution
            error_message = f"Tool '{tool_name}' execution failed with error: {e}"
            logger.exception(error_message) # Log full traceback
            # Re-raise or return an error structure?
            # For now, return the error message for StepProcessor to handle

        # Return either the result or an error indication
        if error_message:
            # Return a dictionary indicating error, matching StepResult.error format loosely
            return {"error": error_message} 
        else:
            # Return the actual result from the tool
            return tool_result

        # Old placeholder:
        # await asyncio.sleep(0.1) # Simulate async work
        # return f"Simulated output for tool '{tool_name}' with args: {arguments}" 