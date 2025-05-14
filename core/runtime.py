from __future__ import annotations
import asyncio, logging
import structlog # Import structlog
from typing import Iterable, AsyncIterable, List, Dict, Any, Optional, Literal
from .schema import Message, Turn, Step
from .registry import Registry
from .errors import ProviderError, ConfigurationError, ToolNotFoundError, ToolExecutionError # Added ToolExecutionError
import uuid # For generating IDs
import time # For timestamps
import json # For parsing LLM plan output
from core.metrics import record_step_execution, record_turn_started, record_turn_completed

# Get structlog logger *after* potential configuration
# Configuration should happen in server.py or main entry point
log = structlog.get_logger(__name__)

"""Core execution logic: TurnManager, PlanExecutor, and StepProcessor."""

# Local application imports
from .models import Plan, StepResult, StepErrorDetails, StepMetrics, Message, Turn, Step # Combined imports
from .config import AppConfig, PersonalityConfig, ToolDefinition # Removed ConfigLoader (not directly used), kept AppConfig
from .events import (
    EventPublisherSubscriber, EventEnvelope, 
    TurnEventPayload, StepEventPayload, StepResultEventPayload, 
    TurnCompletedEventPayload, TurnFailedEventPayload, 
    event_publisher, shutdown_event # Changed event_queue to event_publisher
)
from .context import ContextManager # Assuming ContextManager is defined in core/context.py - Uncomment when ready
from providers.factory import ProviderFactory
from .personality import PersonalityPackManager # PersonalityPackManager is still in core.personality
# from providers.base import ProviderInterface # For type hinting if needed
from providers.exceptions import ProviderError
# Remove direct import causing circular dependency
# from memory.manager import MemoryManager 

class TurnManager:
    """Manages the lifecycle of a single user interaction turn."""
    def __init__(self, 
                 app_config: AppConfig, 
                 plan_executor: 'PlanExecutor', 
                 context_manager: ContextManager, # Uncomment when ContextManager is ready
                 event_publisher: EventPublisherSubscriber,
                 personality_manager: PersonalityPackManager # Add when implemented
                 ):
        self.app_config = app_config
        self.plan_executor = plan_executor
        self.context_manager = context_manager # Uncomment when ContextManager is ready
        self.event_publisher = event_publisher
        self.personality_manager = personality_manager # Add when implemented
        log.info("TurnManager initialized.")

    async def start_turn(self,
                       user_message: Message,
                       personality_id_override: Optional[str] = None,
                       session_id: Optional[str] = None,
                       initial_metadata: Optional[Dict[str, Any]] = None,
                       trace_id: Optional[str] = None # Allow optional trace_id pass-through
                       ) -> str:
        """Starts a new turn, generates a plan, and initiates step execution. Returns the turn_id."""
        
        # --- Generate IDs ---
        turn_id = f"turn_{uuid.uuid4()}"
        # Use provided trace_id or generate a new one
        trace_id = trace_id or f"trace_{uuid.uuid4()}" 
        log.info(f"Starting new turn: turn_id={turn_id}, trace_id={trace_id}, session_id={session_id}")

        # Record that a turn has started
        record_turn_started()

        # --- Get Personality ---
        # Use override, session context (TODO), or default
        personality_id = personality_id_override or self.app_config.core_runtime.default_personality_id
        # TODO: Potentially load personality from session context if no override
        
        personality: Optional[PersonalityConfig] = self.personality_manager.get_personality(personality_id)
        if not personality:
             log.error(f"Personality '{personality_id}' not found. Cannot start turn {turn_id}.")
             # TODO: How to signal failure back to caller immediately? Raise exception? Return specific status?
             # For now, log and raise an error that the API layer should catch.
             raise ValueError(f"Personality '{personality_id}' not found.")
        log.info(f"Using personality: {personality.id} ({personality.name}) for turn {turn_id}")

        # --- Initialize Turn context ---
        turn_data = Turn(
            turn_id=turn_id,
            user_message=user_message,
            personality_id=personality.id, # Use the validated/resolved ID
            metadata=initial_metadata or {},
            trace_id=trace_id,
            session_id=session_id,
            plan=None,
            status="PLANNING", # Initial status
            created_at=time.time(), # Add timestamp
            updated_at=time.time()  # Add timestamp
        )
        # This might just store it initially, or return an enriched version
        turn_data = await self.context_manager.initialize_turn_context(turn_data)
        log.debug(f"Initial turn data created for turn_id: {turn_data.turn_id}")

        # --- Generate Plan ---
        try:
            plan = await self.plan_executor.generate_plan(turn_data, self.context_manager, personality)
            if not plan or not plan.steps:
                log.warning(f"Plan generation resulted in no steps for turn_id: {turn_data.turn_id}")
                turn_data.status = "FAILED"
                turn_data.error = {"reason": "Empty plan generated"}
                turn_data.updated_at = time.time()
                # Save the failed state
                await self.context_manager.save_turn(turn_data) 
                # TODO: Publish TurnFailedEvent
                # We still return the turn_id, but the status indicates failure
                return turn_data.turn_id

            turn_data.plan = plan
            turn_data.status = "PROCESSING" # Status update after plan generation
            turn_data.updated_at = time.time()
            log.info(f"Plan generated with {len(plan.steps)} steps for turn_id: {turn_data.turn_id}")

        except Exception as e:
            log.exception(f"Error during plan generation for turn_id: {turn_data.turn_id}")
            turn_data.status = "FAILED"
            turn_data.error = {"reason": f"Plan generation error: {e}"}
            turn_data.updated_at = time.time()
            # Save the failed state
            await self.context_manager.save_turn(turn_data)
            # TODO: Publish TurnFailedEvent
            # Propagate the exception or return turn_id with failed status?
            # Let's re-raise for now, assuming API layer handles it.
            raise # Re-raise the exception after saving state

        # --- Save Turn State (with Plan) ---
        try:
            await self.context_manager.save_turn(turn_data)
            log.debug(f"Saved initial turn state with plan for turn_id: {turn_data.turn_id}")
        except Exception as e:
            # If saving fails, we are in a bad state. Log critical error.
            log.critical(f"CRITICAL: Failed to save initial turn state for turn_id: {turn_data.turn_id}. Error: {e}")
            # TODO: What happens now? The turn processing might continue without persistence.
            # Maybe try to update status to FAILED again?
            turn_data.status = "FAILED"
            turn_data.error = {"reason": f"Failed to save initial turn state: {e}"}
            # Re-raise or handle? Re-raising might be best.
            raise

        # --- Publish StepEvents ---
        log.info(f"Publishing StepEvents for plan {plan.plan_id} (turn: {turn_id})...")
        for step_to_execute in plan.steps:
            step_event_payload = StepEventPayload(
                personality_id=personality.id, # Include personality_id
                **step_to_execute.model_dump()
            )
            step_event = EventEnvelope(
                event_id=str(uuid.uuid4()),
                type="StepEvent",
                spec_version="1.0.0",
                trace_id=trace_id,
                session_id=session_id,
                payload=step_event_payload
            )
            try:
                await self.event_publisher.publish(step_event)
                log.debug(f"Published StepEvent for step_id: {step_to_execute.step_id}")
            except Exception as e:
                # If publishing fails, log error but potentially continue?
                # Or should this fail the turn? Failing seems safer.
                log.error(f"Failed to publish StepEvent for step {step_to_execute.step_id}, turn {turn_id}. Error: {e}")
                # Update turn status?
                # TODO: Decide on error handling for event publishing failures.
                # For now, log and continue, subsequent steps won't run.


        log.info(f"Turn processing initiated for turn_id: {turn_data.turn_id}. Returning ID.")
        return turn_data.turn_id # Return the ID of the initiated turn

    async def handle_step_result_event(self, result_envelope: EventEnvelope):
        """Handles incoming StepResultEvents to track turn progress and finalize the turn."""
        if not isinstance(result_envelope.payload, StepResultEventPayload):
            log.error(f"Received non-StepResultEventPayload in handle_step_result_event: {result_envelope.type}")
            return

        result_payload: StepResultEventPayload = result_envelope.payload
        turn_id = result_payload.turn_id
        step_id = result_payload.step_id
        plan_id = result_payload.plan_id
        trace_id = result_envelope.trace_id
        session_id = result_envelope.session_id

        log.info(f"Handling StepResultEvent: turn_id={turn_id}, step_id={step_id}, status={result_payload.status}, trace_id={trace_id}")

        # --- Retrieve Turn Context ---
        try:
            # TODO: Implement ContextManager.get_turn()
            turn_data: Optional[Turn] = await self.context_manager.get_turn(turn_id)
            if not turn_data:
                log.warning(f"Received StepResultEvent for unknown or already completed turn_id: {turn_id}. Discarding event for step {step_id}.")
                return
            # Basic check: ensure the plan ID matches
            if not turn_data.plan or turn_data.plan.plan_id != plan_id:
                log.warning(f"Received StepResultEvent for step {step_id} with mismatched plan_id ({plan_id}) for turn {turn_id}. Expected {turn_data.plan.plan_id if turn_data.plan else 'None'}. Discarding event.")
                return
        except Exception as e:
            log.exception(f"Failed to retrieve turn context for turn_id {turn_id} while processing step result {step_id}. Error: {e}")
            # Cannot proceed without turn context
            return

        # --- Update Step Result in Turn Data ---
        step_updated = False
        target_step: Optional[Step] = None
        for step in turn_data.plan.steps:
            if step.step_id == step_id:
                target_step = step
                # Avoid overwriting a final state if event is duplicated/late
                if target_step.result and target_step.result.status in ["SUCCEEDED", "FAILED"]:
                    log.warning(f"Received duplicate/late StepResultEvent for already completed step {step_id} (status: {target_step.result.status}). Ignoring.")
                    return # Ignore late/duplicate events for completed steps
                    
                # Create the StepResult object based on payload
                step_metrics_obj: Optional[StepMetrics] = None
                if result_payload.metrics:
                    try:
                        step_metrics_obj = StepMetrics.model_validate(result_payload.metrics)
                    except Exception as e:
                        log.warning(f"Failed to parse StepMetrics from event payload for step {step_id}. Error: {e}. Metrics will be ignored.")
                
                # TODO: Need to handle error payload parsing as well if it's complex
                # step_error_obj: Optional[StepErrorDetails] = None
                # if result_payload.error:
                #    try: step_error_obj = StepErrorDetails.model_validate(result_payload.error)
                #    except: pass # Log warning
                
                step_result = StepResult(
                    step_id=step_id,
                    status=result_payload.status,
                    output=result_payload.output,
                    error=result_payload.error, # Assuming payload error structure matches StepErrorDetails implicitly for now
                    # error=step_error_obj # Use parsed object if implemented
                    metrics=step_metrics_obj # Store parsed StepMetrics object
                    # TODO: Potentially parse/validate error/metrics structures from payload dicts
                )
                target_step.result = step_result
                turn_data.updated_at = time.time() # Update turn timestamp
                step_updated = True
                log.info(f"Updated result for step {step_id} in turn {turn_id} to status: {step_result.status}")
                break

        if not step_updated:
            log.warning(f"Step {step_id} not found in plan {plan_id} for turn {turn_id}. Cannot update result.")
            # Don't save if nothing changed, but maybe log inconsistency?
            return

        # --- Check for Turn Completion ---
        all_steps_completed = True
        any_step_failed = False
        final_output = None # Placeholder for final turn output

        if not turn_data.plan or not turn_data.plan.steps:
             log.error(f"Turn {turn_id} has no plan or steps after updating step {step_id}. Cannot determine completion.")
             all_steps_completed = False # Cannot be complete
        else:
            for step in turn_data.plan.steps:
                if not step.result or step.result.status not in ["SUCCEEDED", "FAILED"]:
                    all_steps_completed = False
                    break # Found an incomplete step
                if step.result.status == "FAILED":
                    any_step_failed = True
                # simplistic: Use the output of the last successful step as final output for now
                if step.result.status == "SUCCEEDED":
                    final_output = step.result.output 

        # --- Process Turn Completion (if applicable) ---
        if all_steps_completed:
            log.info(f"All steps completed for turn {turn_id}. Finalizing turn.")
            final_turn_status = "FAILED" if any_step_failed else "SUCCEEDED"
            turn_data.status = final_turn_status
            turn_data.updated_at = time.time()

            # Record that a turn has completed
            record_turn_completed(status=final_turn_status)

            if final_turn_status == "SUCCEEDED":
                turn_data.output = final_output
                final_payload = TurnCompletedEventPayload(
                    turn_id=turn_id,
                    final_output=final_output,
                    # TODO: Populate metrics
                    metrics=None 
                )
                final_event_type = "TurnCompletedEvent"
            else:
                # Find the first failed step's error details
                first_error = None
                for step in turn_data.plan.steps:
                    if step.result and step.result.status == "FAILED":
                        first_error = step.result.error or {"kind": "UnknownStepError", "detail": f"Step {step.step_id} failed without details."}
                        break
                turn_data.error = first_error or {"kind": "UnknownTurnError", "detail": "Turn failed, but no specific step error found."} 
                final_payload = TurnFailedEventPayload(
                    turn_id=turn_id,
                    error=turn_data.error,
                    # TODO: Populate metrics
                    metrics=None 
                )
                final_event_type = "TurnFailedEvent"

            # --- Save Final Turn State ---
            try:
                # TODO: Implement ContextManager.save_turn()
                await self.context_manager.save_turn(turn_data)
                log.info(f"Saved final state for turn {turn_id} with status: {final_turn_status}")
            except Exception as e:
                log.critical(f"CRITICAL: Failed to save final state for completed turn {turn_id}. Error: {e}. Final event might not be published.")
                # Should we still try to publish the event?
                # Let's proceed to publish for now, but the persisted state might be inconsistent.

            # --- Publish Final Turn Event ---
            final_event = EventEnvelope(
                event_id=str(uuid.uuid4()),
                type=final_event_type,
                spec_version="1.0.0", # Use appropriate version
                trace_id=trace_id,
                session_id=session_id,
                payload=final_payload
            )
            try:
                await self.event_publisher.publish(final_event)
                log.info(f"Published final event {final_event_type} for turn {turn_id}.")
            except Exception as e:
                log.error(f"Failed to publish final event {final_event_type} for turn {turn_id}. Error: {e}")
        
        else:
            # --- Turn Not Complete: Save Intermediate State ---
            log.debug(f"Turn {turn_id} not yet complete. Saving intermediate state after processing step {step_id}.")
            try:
                # TODO: Implement ContextManager.save_turn()
                await self.context_manager.save_turn(turn_data)
            except Exception as e:
                log.error(f"Failed to save intermediate state for turn {turn_id} after step {step_id}. Error: {e}")
                # Turn processing might continue, but state isn't persisted.

class PlanExecutor:
    """Responsible for generating a plan based on user input and context."""
    # Use string literal for type hint for MemoryManager
    def __init__(
        self,
        provider_factory: ProviderFactory,
        event_publisher: EventPublisherSubscriber,
        personality_manager: PersonalityPackManager,
        memory_manager: 'MemoryManager' # <-- String hint here
    ):
        """Initializes the PlanExecutor."""
        self.provider_factory = provider_factory
        self.event_publisher = event_publisher
        self.personality_manager = personality_manager
        self.memory_manager = memory_manager # Store memory manager
        # Simple registry for prompt templates (can be expanded)
        self.prompt_registry: Dict[str, str] = {} # NEW - Use a simple dict
        self._register_default_prompts()
        log.info("PlanExecutor initialized.")

    def _register_default_prompts(self):
        # Placeholder for a more robust prompt management system
        # In a real system, these would likely be loaded from files or a dedicated config
        default_plan_prompt = (
            "You are an expert planning agent. Based on the user request and conversation history, "
            "create a step-by-step plan to fulfill the request. "
            "Use the available tools provided by the personality. "
            "Output the plan as a JSON object containing a list of steps, where each step has: "
            "- step_id (string, unique identifier) "
            "- type (string, e.g., 'tool_call', 'llm_call', 'memory_op') "
            "- description (string, human-readable description) "
            "- parameters (object, specific parameters for the step type, e.g., tool_name, args for tool_call) "
            
            "Available Tools:"
            "{tools_description}"
            
            "Conversation History:"
            "{history}"
            
            "User Request:"
            "{user_request}"
            
            "Respond ONLY with the JSON plan object."
        )
        self.prompt_registry["default_plan"] = default_plan_prompt # NEW - Dict assignment
        log.debug("Registered default planning prompt.")

    def _format_turn_messages_for_prompt(self, messages: List[Message]) -> str:
        # Simple formatting, can be enhanced (e.g., handle different roles)
        return "\n".join([f"{msg.role}: {msg.content}" for msg in messages])

    async def generate_plan(self, turn: Turn, context_manager: ContextManager, personality: PersonalityConfig) -> Optional[Plan]:
        """Generates a plan (sequence of steps) based on the current turn context and personality, optionally augmented by memory search."""
        log.info(f"Generating plan for turn_id: {turn.turn_id} using personality: {personality.id}")

        # --- Get Conversation History (if needed for prompt) ---
        # Assuming ContextManager handles history retrieval if integrated
        # history: List[Message] = await context_manager.get_conversation_history(turn.session_id)
        # history_str = self._format_turn_messages_for_prompt(history)
        # For now, just use the current user message
        history_str = self._format_turn_messages_for_prompt([turn.user_message])

        # --- Get Available Tools from Personality ---
        tool_list_str = "\n".join([f"- {tool.name}: {tool.description}" for tool in personality.tools])

        # --- Perform Memory Search (Optional Context Augmentation) ---
        memory_context_str = ""
        if self.memory_manager:
            try:
                log.debug(f"Performing memory search for turn {turn.turn_id} with query: {turn.user_message.content[:100]}...")
                search_results = await self.memory_manager.search(query=turn.user_message.content, top_k=3) # Limit to top 3 for prompt brevity
                if search_results:
                    formatted_results = []
                    for i, result in enumerate(search_results):
                        # Extract text, handle potential missing keys gracefully
                        text = result.get('text', 'N/A')
                        # Basic formatting, limiting length
                        formatted_results.append(f"  {i+1}. {text[:200]}{'...' if len(text) > 200 else ''}") 
                    memory_context_str = "\nRelevant context from memory:\n" + "\n".join(formatted_results)
                    log.info(f"Added {len(search_results)} results from memory search to planning prompt for turn {turn.turn_id}")
                else:
                    log.info(f"Memory search returned no results for turn {turn.turn_id}")
            except Exception as e:
                log.warning(f"Memory search failed for turn {turn.turn_id}. Proceeding without memory context. Error: {e}", exc_info=True)
        else:
            log.debug("MemoryManager not available, skipping memory search for planning.")

        # --- Select Planning Prompt Template ---
        # Use personality's prompt template if available, otherwise default
        # Access using .get() for dictionaries
        prompt_template_str = personality.plan_prompt_template or self.prompt_registry.get("default_plan")
        if not prompt_template_str:
             log.error(f"No planning prompt template found for personality {personality.id} or default. Cannot generate plan.")
             raise ValueError("Missing planning prompt template.")

        # --- Construct the Full Prompt ---
        # Combine memory context with the main prompt template
        # Prepend memory context if available
        full_prompt_str = f"{memory_context_str}\n\n{prompt_template_str}"

        # --- Format the Prompt with Turn Data ---
        try:
            formatted_prompt = full_prompt_str.format(
                tool_list=tool_list_str,
                history=history_str, # Or potentially use turn.conversation_history if populated
                user_request=turn.user_message.content
                # Add other potential placeholders like system_prompt from personality?
            )
        except KeyError as e:
            log.error(f"Missing key in planning prompt template for personality {personality.id}: {e}")
            raise ValueError(f"Invalid planning prompt template: Missing key {e}")

        # --- Select Provider based on Personality ---
        provider_id = personality.plan_provider_id or self.provider_factory.get_default_provider_id()
        if not provider_id:
             log.error(f"No planning provider configured for personality {personality.id} and no default provider found.")
             raise ValueError("Missing planning provider configuration.")

        planning_provider = self.provider_factory.get_provider(provider_id)
        if not planning_provider:
            log.error(f"Planning provider '{provider_id}' not found or failed to initialize.")
            raise ValueError(f"Invalid planning provider: {provider_id}")

        log.info(f"Using provider '{provider_id}' for plan generation for turn {turn.turn_id}")

        # --- Call LLM for Plan Generation ---
        try:
            log.debug(f"Sending planning prompt to provider {provider_id} for turn {turn.turn_id}:\n{formatted_prompt[:500]}...") # Log truncated prompt
            # Assuming generate method takes a simple string prompt
            # TODO: Adapt if the provider expects a structured input (e.g., messages list)
            response = await planning_provider.generate(
                model=personality.plan_model or planning_provider.get_default_model(), # Use personality model or provider default
                prompt=formatted_prompt,
                # TODO: Add other parameters like max_tokens, temperature from personality/config?
            )
            plan_json_str = response.text # Assuming response has a 'text' attribute with the JSON string
            log.debug(f"Received raw plan response from provider for turn {turn.turn_id}: {plan_json_str[:500]}...")
        except ProviderError as e:
            log.error(f"Provider error during plan generation for turn {turn.turn_id}: {e}")
            # TODO: Map provider errors to internal state/error reporting
            raise # Re-raise for now
        except Exception as e:
            log.exception(f"Unexpected error during plan generation LLM call for turn {turn.turn_id}: {e}")
            raise # Re-raise for now

        # --- Parse Plan Response ---
        try:
            # Attempt to clean up potential markdown code fences
            if plan_json_str.strip().startswith("```json"):
                plan_json_str = plan_json_str.strip()[7:]
            if plan_json_str.strip().endswith("```"):
                plan_json_str = plan_json_str.strip()[:-3]
            
            plan_data = json.loads(plan_json_str)
            if "steps" not in plan_data or not isinstance(plan_data["steps"], list):
                raise ValueError("Plan JSON missing 'steps' list.")

            # Construct Plan and Step objects using Pydantic models for validation
            plan_id = f"plan_{turn.turn_id}" # Simple plan ID based on turn ID
            steps = []
            for i, step_data in enumerate(plan_data["steps"]):
                # Add plan_id and step_index automatically
                step_id = f"step_{plan_id}_{i}"
                step_data['plan_id'] = plan_id
                step_data['step_id'] = step_id
                step_data['step_index'] = i
                # Validate using the Step model
                steps.append(Step.model_validate(step_data))

            plan = Plan(plan_id=plan_id, turn_id=turn.turn_id, steps=steps)
            log.info(f"Successfully parsed plan {plan.plan_id} with {len(plan.steps)} steps for turn {turn.turn_id}.")
            return plan

        except json.JSONDecodeError as e:
            log.error(f"Failed to decode JSON plan response for turn {turn.turn_id}. Response: {plan_json_str}. Error: {e}")
            # TODO: Implement retry logic or error handling for malformed plans
            return None # Indicate plan generation failure
        except Exception as e:
            log.exception(f"Error parsing or validating plan structure for turn {turn.turn_id}. Error: {e}")
            return None # Indicate plan generation failure

class StepProcessor:
    """Executes individual steps from a plan."""
    def __init__(self, 
                 app_config: AppConfig, 
                 provider_factory: ProviderFactory, 
                 context_manager: ContextManager, 
                 event_publisher: EventPublisherSubscriber,
                 personality_manager: PersonalityPackManager,
                 memory_manager: 'MemoryManager' # Add memory manager type hint if needed
                 ):
        self.app_config = app_config
        self.provider_factory = provider_factory
        self.context_manager = context_manager
        self.event_publisher = event_publisher
        self.personality_manager = personality_manager
        self.memory_manager = memory_manager # Store memory manager if used
        log.info("StepProcessor initialized.")

    async def handle_step_event(self, step_payload: StepEventPayload) -> None:
        """Handles a StepEvent by executing the specified tool or action."""
        turn_id = step_payload.turn_id
        plan_id = step_payload.plan_id
        step_id = step_payload.step_id
        personality_id = step_payload.personality_id # Added in TASK-002
        log.info(f"StepProcessor handling step '{step_id}' for turn '{turn_id}', plan '{plan_id}' with personality '{personality_id}'")

        step_output_data: Optional[Any] = None
        step_error_message: Optional[str] = None
        step_metrics: Optional[StepMetrics] = None
        status: Literal["SUCCEEDED", "FAILED", "RETRYING", "CANCELLED"] # Add type hint
        start_time = time.time() # For latency calculation

        try:
            # Attempt to get the specific personality config
            personality = self.personality_manager.get_personality(personality_id) if self.personality_manager else None
            if not personality:
                log.error(f"Personality '{personality_id}' not found. Cannot execute step '{step_id}'.")
                raise ValueError(f"Personality '{personality_id}' not found.")

            # --- Execute Step based on Type ---
            step_type = step_payload.step_type
            step_params = step_payload.parameters or {} # Old: step_params, New: step_config from payload
            step_config = step_payload.step_config or {} # Use step_config for provider/model overrides
            step_inputs = step_payload.inputs or {}

            if step_type == "llm_generate": # Renamed from LLM_CALL
                log.info(f"Executing llm_generate step '{step_id}' for turn '{turn_id}'")

                # 1. Prepare messages for the provider
                final_messages: List[Message] = []
                
                # Add system prompt from personality
                if personality.system_prompt:
                    final_messages.append(Message(role="system", content=personality.system_prompt))
                
                # Add user/assistant messages from inputs
                if "messages" in step_inputs and isinstance(step_inputs["messages"], list):
                    for msg_data in step_inputs["messages"]:
                        if isinstance(msg_data, dict) and "role" in msg_data and "content" in msg_data:
                            final_messages.append(Message(role=msg_data["role"], content=msg_data["content"]))
                        else:
                            log.warning(f"Skipping malformed message data in 'messages' input for step {step_id}: {msg_data}")
                elif "prompt" in step_inputs and isinstance(step_inputs["prompt"], str):
                    final_messages.append(Message(role="user", content=step_inputs["prompt"]))
                else:
                    raise ValueError("llm_generate step requires 'messages' (list of dicts) or 'prompt' (string) in inputs.")

                if not any(msg.role == "user" for msg in final_messages):
                    # Add a dummy user message if none, to prevent errors with some models,
                    # though ideally the plan should ensure a user message.
                    # Or raise ValueError if no user message explicitly provided.
                    # For now, let's be a bit more robust, but this might need review.
                    log.warning(f"No user message in 'inputs' for llm_generate step {step_id}. Plan should include user input.")
                    # raise ValueError("llm_generate step requires at least one user message in 'inputs'.")


                # 2. Determine provider, model, and parameters
                # Provider ID
                provider_id = step_config.get("provider_id", personality.provider_id) # personality.provider_id should exist
                if not provider_id: # Fallback to app default if not in personality (should be rare)
                    provider_id = self.app_config.core_runtime.default_provider
                
                # Model Name & Parameters
                # Start with AppConfig defaults for the chosen provider
                provider_app_config = self.app_config.providers.get(provider_id)
                if not provider_app_config or not provider_app_config.llm:
                    raise ConfigurationError(f"LLM configuration not found for provider '{provider_id}' in AppConfig.")

                # Base model name and parameters from AppConfig
                model_name = provider_app_config.llm.model
                model_parameters = provider_app_config.llm.parameters.copy() if provider_app_config.llm.parameters else {}

                # Override with Personality's LLM config (if personality defines specific llm settings)
                if personality.llm: # personality.llm should be an LLMConfig object
                    if personality.llm.model: # Personality can override model
                        model_name = personality.llm.model
                    if personality.llm.parameters: # Personality can override/add params
                        model_parameters.update(personality.llm.parameters)
                
                # Override with Step-specific config (highest priority)
                if "model_name" in step_config:
                    model_name = step_config["model_name"]
                
                # For model parameters in step_config, merge them in.
                # Example: step_config might have {"temperature": 0.9, "max_tokens": 100}
                # These should override anything from personality or app_config.
                # We need a clear definition of what goes into step_config.model_parameters vs. flat in step_config
                # For now, assume flat overrides in step_config for known LLM params
                for param_key in ["temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"]: # Common params
                    if param_key in step_config:
                        model_parameters[param_key] = step_config[param_key]
                
                stream = step_config.get("stream", personality.llm.stream if personality.llm else False) # Default to False

                if not provider_id or not model_name:
                    raise ConfigurationError(f"Could not resolve provider_id ('{provider_id}') or model_name ('{model_name}') for llm_generate step.")

                # 3. Get provider and generate
                # The factory now takes personality_config, which might influence how a provider is set up
                provider = await self.provider_factory.get_provider(provider_id, self.app_config, personality)
                if not provider:
                     raise ConfigurationError(f"Provider '{provider_id}' not found or failed to initialize for llm_generate step.")
                
                log.info(f"Executing llm_generate step '{step_id}' using provider '{provider_id}', model '{model_name}'")
                
                # Provider's generate method should return a Message object and handle its own metrics (tokens, cost)
                # The `record_llm_request` should be called *inside* the provider.
                response_message: Message = await provider.generate(
                    messages=final_messages,
                    model_name=model_name,
                    stream=stream, 
                    **model_parameters 
                )
                
                step_output_data = response_message.model_dump() # As per test assertion
                status = "SUCCEEDED"
                log.info(f"llm_generate step '{step_id}' completed.")
                # Metrics: Latency is calculated below. Token/cost metrics should be handled by the provider via record_llm_request.
                # For StepMetrics here, we mostly care about latency if provider handles the rest.
                # The old LLMResponse carried cost/tokens directly. If Message doesn't, this needs thought.
                # For now, let's assume StepMetrics will primarily hold latency if provider records other LLM metrics.
                # If `record_llm_request` is called by the provider, it updates global metrics.
                # The StepResultEventPayload.metrics will then just show step-specific processing time.

            elif step_type == "llm_embed":
                log.info(f"Executing llm_embed step '{step_id}' for turn '{turn_id}'")

                # 1. Get texts to embed from inputs
                if "texts_to_embed" not in step_inputs or not isinstance(step_inputs["texts_to_embed"], list):
                    raise ValueError("llm_embed step requires 'texts_to_embed' (list of strings) in inputs.")
                texts_to_embed: List[str] = step_inputs["texts_to_embed"]
                if not all(isinstance(text, str) for text in texts_to_embed):
                    raise ValueError("All items in 'texts_to_embed' must be strings.")

                # 2. Determine provider, model, and parameters for embedding
                # Provider ID for embedding
                # Assumes PersonalityConfig has embedding_provider_id or similar dedicated field
                # For now, let's assume personality.embedding_config.provider_id or personality.embedding_provider_id
                # Let's try to use a generic approach: personality might have an 'embedding' LLMConfig-like object.
                # Or we assume the main provider_id is used, and ProviderFactory differentiates.
                # For clarity, let's assume personality can specify an embedding_provider_id.
                # If not, it falls back to the main provider_id of the personality, assuming that provider also does embeddings.
                
                default_embedding_provider = self.app_config.core_runtime.default_embedding_provider # Needs to be added to CoreRuntimeConfig
                
                # Option A: Personality has a dedicated embedding_provider_id and embedding_model_config
                # This is cleaner if embedding is a distinct function.
                # We need to define these fields in PersonalityConfig and AppConfig.ProviderConfig.embedding
                
                # Let's assume PersonalityConfig has: embedding_settings: Optional[EmbeddingProviderSettings]
                # where EmbeddingProviderSettings has provider_id, model_name, parameters.
                # And AppConfig.providers[provider_id].embedding_config: Optional[EmbeddingModelConfig]
                
                # Simplified approach for now: Use personality's main provider_id if not overridden by step_config.
                # The ProviderConfig for that provider in AppConfig must then have an 'embedding' section.

                provider_id = step_config.get("provider_id", personality.provider_id) # Default to personality's main provider
                if not provider_id: # Highly unlikely if personality is valid
                    provider_id = default_embedding_provider # Or app_config.core_runtime.default_provider

                provider_app_config = self.app_config.providers.get(provider_id)
                if not provider_app_config or not provider_app_config.embedding: # Crucially, check for .embedding config
                    raise ConfigurationError(f"Embedding configuration not found for provider '{provider_id}' in AppConfig.")

                # Base embedding model name and parameters from AppConfig provider's embedding config
                embedding_model_name = provider_app_config.embedding.model
                embedding_parameters = provider_app_config.embedding.parameters.copy() if provider_app_config.embedding.parameters else {}

                # Override with Personality's embedding config (if personality has specific embedding settings)
                # This assumes personality.embedding is an EmbeddingConfig object.
                if hasattr(personality, 'embedding') and personality.embedding and isinstance(personality.embedding, EmbeddingConfig):
                    if personality.embedding.model:
                        embedding_model_name = personality.embedding.model
                    if personality.embedding.parameters:
                        embedding_parameters.update(personality.embedding.parameters)
                
                # Override with Step-specific config (highest priority)
                if "embedding_model_name" in step_config: # or just model_name if context is clear
                    embedding_model_name = step_config["embedding_model_name"]
                # Merge step_config parameters for embedding
                for param_key in step_config.get("embedding_parameters", {}).keys(): # e.g. embedding_parameters: { "normalize": True }
                    embedding_parameters[param_key] = step_config["embedding_parameters"][param_key]
                
                if not provider_id or not embedding_model_name:
                    raise ConfigurationError(f"Could not resolve provider_id ('{provider_id}') or embedding_model_name ('{embedding_model_name}') for llm_embed step.")

                # 3. Get provider and embed
                # ProviderFactory needs to know this is for an embedding task if the same provider_id can do both chat & embed
                # For now, assume get_provider returns a provider capable of .embed() based on its config.
                provider = await self.provider_factory.get_provider(provider_id, self.app_config, personality)
                if not provider:
                     raise ConfigurationError(f"Provider '{provider_id}' not found or failed to initialize for llm_embed step.")
                
                log.info(f"Executing llm_embed step '{step_id}' using provider '{provider_id}', model '{embedding_model_name}'")
                
                embeddings: List[List[float]] = await provider.embed(
                    texts=texts_to_embed,
                    model_name=embedding_model_name,
                    **embedding_parameters
                )
                
                step_output_data = {"embeddings": embeddings}
                status = "SUCCEEDED"
                log.info(f"llm_embed step '{step_id}' completed.")
                # Metrics for embedding (latency below, tokens/cost by provider if supported)

            elif step_type == "TOOL_CALL":
                # Use step_config for consistency with llm_generate and llm_embed
                tool_name = step_config.get("tool_name")
                tool_args = step_config.get("args", {}) # Ensure 'args' is the key from step_config

                if not tool_name:
                    raise ValueError("Missing 'tool_name' in step_config for TOOL_CALL step.")
                if not isinstance(tool_args, dict): # Validate tool_args structure
                    raise ValueError("'args' must be a dictionary in step_config for TOOL_CALL step.")

                log.info(f"Executing TOOL_CALL step '{step_id}' for turn '{turn_id}' with tool_name: '{tool_name}'")

                # Check for built-in memory tools first
                if tool_name == "search_memory":
                    if not self.memory_manager:
                        raise RuntimeError("MemoryManager not available for search_memory tool.")
                    # Validate specific args for search_memory
                    query = tool_args.get("query")
                    if not query or not isinstance(query, str):
                        raise ValueError("Missing or invalid 'query' (string) for search_memory tool args.")
                    top_k = tool_args.get("top_k", 5)
                    if not isinstance(top_k, int):
                        raise ValueError("Invalid 'top_k' (must be int) for search_memory tool args.")
                    filters = tool_args.get("filters")
                    if filters and not isinstance(filters, dict): # Allow filters to be None
                        raise ValueError("Invalid 'filters' (must be dict) for search_memory tool args.")
                    
                    step_output_data = await self.memory_manager.search(query=query, top_k=top_k, filters=filters)
                    status = "SUCCEEDED"
                    log.info(f"Memory tool 'search_memory' executed for step '{step_id}'.")

                elif tool_name == "retrieve_from_memory":
                    if not self.memory_manager:
                        raise RuntimeError("MemoryManager not available for retrieve_from_memory tool.")
                    doc_id = tool_args.get("doc_id")
                    if not doc_id or not isinstance(doc_id, str):
                        raise ValueError("Missing or invalid 'doc_id' (string) for retrieve_from_memory tool args.")

                    retrieved_doc = await self.memory_manager.read(key=doc_id) # Assuming MemoryManager.read is the correct method
                    step_output_data = retrieved_doc 
                    status = "SUCCEEDED"
                    log.info(f"Memory tool 'retrieve_from_memory' executed for step '{step_id}'.")
                
                elif tool_name == "add_to_memory":
                    if not self.memory_manager:
                        raise RuntimeError("MemoryManager not available for add_to_memory tool.")
                    # Define expected args for add_to_memory from tool_args
                    doc_id = tool_args.get("doc_id")
                    text_content = tool_args.get("text") # Assuming 'text' holds the primary content
                    metadata = tool_args.get("metadata", {}) # Optional metadata

                    if not doc_id or not text_content:
                        raise ValueError("Missing or invalid 'doc_id' or 'text' for add_to_memory tool args.")
                    if not isinstance(metadata, dict):
                        raise ValueError("Invalid 'metadata' (must be dict) for add_to_memory tool args.")

                    # Assuming MemoryManager.write takes key and a data dict
                    await self.memory_manager.write(key=doc_id, data={"text": text_content, "metadata": metadata})
                    step_output_data = {"status": "write successful", "doc_id": doc_id}
                    status = "SUCCEEDED"
                    log.info(f"Memory tool 'add_to_memory' executed for step '{step_id}'.")

                elif tool_name == "delete_from_memory":
                    if not self.memory_manager:
                        raise RuntimeError("MemoryManager not available for delete_from_memory tool.")
                    doc_id = tool_args.get("doc_id")
                    if not doc_id or not isinstance(doc_id, str):
                        raise ValueError("Missing or invalid 'doc_id' (string) for delete_from_memory tool args.")

                    await self.memory_manager.delete(key=doc_id)
                    step_output_data = {"status": "delete successful", "doc_id": doc_id}
                    status = "SUCCEEDED"
                    log.info(f"Memory tool 'delete_from_memory' executed for step '{step_id}'.")

                else: # Delegate to PersonalityPackManager for non-built-in tools
                    if not self.personality_manager:
                        raise RuntimeError("PersonalityPackManager not available for tool execution.")
                    if not personality: # Should have been loaded at the start of handle_step_event
                         raise ConfigurationError(f"Personality not loaded for turn '{turn_id}', cannot execute tool '{tool_name}'.")

                    log.info(f"Delegating tool '{tool_name}' to PersonalityManager for personality '{personality.id}'. Step: {step_id}")
                    try:
                        tool_result = await self.personality_manager.execute_tool(
                            personality_id=personality.id, 
                            tool_name=tool_name,
                            tool_args=tool_args,
                        )
                        step_output_data = tool_result
                        status = "SUCCEEDED"
                        log.info(f"Tool '{tool_name}' executed successfully via PersonalityManager for step '{step_id}'.")
                    except ToolNotFoundError as e:
                        log.warning(f"Tool '{tool_name}' not found by PersonalityManager for personality '{personality.id}'. Step: {step_id}. Error: {e}")
                        error_message = str(e)
                        status = "FAILED"
                    except ToolExecutionError as e: # Catch specific ToolExecutionError
                        log.error(f"ToolExecutionError for tool '{tool_name}' in personality '{personality.id}' for step '{step_id}': {e}", exc_info=True)
                        # We might want to use the message from e directly, or format a standard one.
                        # The current e.__str__() includes the original error, which is good.
                        error_message = str(e) 
                        status = "FAILED"
                    except Exception as e: # General fallback
                        log.error(f"Unexpected error executing tool '{tool_name}' via PersonalityManager for step '{step_id}': {e}", exc_info=True)
                        error_message = f"Unexpected execution error in tool '{tool_name}' via PersonalityManager: {str(e)}"
                        status = "FAILED"
            
            elif step_type == "MEMORY_OP":
                # Example: Write to memory
                op_type = step_params.get("operation")
                if op_type == "write":
                    if not self.memory_manager:
                         raise RuntimeError("MemoryManager not available for MEMORY_OP step.")
                    doc_id = step_params.get("doc_id")
                    doc_text = step_params.get("text")
                    doc_metadata = step_params.get("metadata", {})
                    if not doc_id or not doc_text:
                        raise ValueError("Missing 'doc_id' or 'text' for MEMORY_OP write step.")
                    
                    await self.memory_manager.write(key=doc_id, data={"text": doc_text, "metadata": doc_metadata})
                    step_output_data = {"status": "write successful", "doc_id": doc_id}
                    status = "SUCCEEDED"
                    log.info(f"MEMORY_OP 'write' executed for step '{step_id}'.")
                elif op_type == "delete":
                     if not self.memory_manager:
                         raise RuntimeError("MemoryManager not available for MEMORY_OP step.")
                     doc_id = step_params.get("doc_id")
                     if not doc_id:
                         raise ValueError("Missing 'doc_id' for MEMORY_OP delete step.")
                     await self.memory_manager.delete(key=doc_id)
                     step_output_data = {"status": "delete successful", "doc_id": doc_id}
                     status = "SUCCEEDED"
                     log.info(f"MEMORY_OP 'delete' executed for step '{step_id}'.")
                else:
                    raise ValueError(f"Unsupported MEMORY_OP operation: {op_type}")
            
            # Add other step types like EXTERNAL_API?
            
            else:
                raise ValueError(f"Unsupported step type: {step_type}")

        except Exception as e:
            log.error(f"Error executing step '{step_id}' for turn '{turn_id}': {e}", exc_info=True)
            step_error_message = str(e)
            status = "FAILED"
        
        latency_ms = (time.time() - start_time) * 1000
        # If step_metrics wasn't populated by a provider/tool, create basic one
        if not step_metrics:
            step_metrics = StepMetrics(latency_ms=latency_ms)
        else:
            step_metrics.latency_ms = latency_ms # Ensure latency is always set

        # Record metrics for this step
        record_step_execution(step_type=step_payload.step_type, status=status)

        # Publish StepResultEvent
        result_payload = StepResultEventPayload(
            turn_id=turn_id,
            plan_id=plan_id,
            step_id=step_id,
            status=status,
            output=step_output_data, # Can be string, dict, list, etc.
            error=step_error_message,
            metrics=step_metrics.model_dump() # Convert Pydantic model to dict for event
        )
        if self.event_publisher:
            await self.event_publisher.publish("step_result", result_payload)
            log.info(f"Published step result for step '{step_id}'. Status: {status}")
        else:
            log.error("Event publisher not available. Cannot publish step result.")