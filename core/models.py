"""Core data structures (Turn, Plan, Step, etc.)."""

from datetime import datetime
from typing import Literal, Optional, Any, Dict, List
from pydantic import BaseModel, Field
import time # For timestamps

# --- Core Message Structure ---

class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    # Could add timestamp, message_id etc. later if needed

# --- Turn Lifecycle --- Data primarily for TurnEvent payload ---

class Turn(BaseModel):
    turn_id: str = Field(..., description="Unique ID for this specific turn")
    user_message: Message # Assuming the initial message fits the Message model
    personality_id: str = Field(..., description="ID of the personality context to use")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional key-value pairs for extra context")
    # Runtime fields added by TurnManager/ContextManager (not part of TurnEvent)
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    conversation_history: List[Message] = []
    turn_context: Dict[str, Any] = {}
    plan: Optional['Plan'] = None # Added Optional and forward ref
    # Fields for tracking turn state and outcome
    status: str = Field(default="PENDING", description="Current status: PENDING, PLANNING, PROCESSING, SUCCEEDED, FAILED")
    output: Optional[Any] = Field(None, description="Final output/response of the turn, if successful")
    error: Optional[Dict[str, Any]] = Field(None, description="Error details if the turn failed")
    created_at: Optional[float] = Field(default_factory=time.time, description="Unix timestamp of turn creation")
    updated_at: Optional[float] = Field(default_factory=time.time, description="Unix timestamp of last turn update")

# --- Step Execution --- Data primarily for StepEvent payload ---

class Step(BaseModel):
    plan_id: str = Field(..., description="ID of the parent plan")
    step_id: str = Field(..., description="Unique ID for this step")
    step_index: int = Field(..., ge=0, description="Sequence position within the plan")
    step_type: Literal["LLM_CALL", "TOOL_CALL", "MEMORY_OP", "EXTERNAL_API"] = Field(..., description="Type of action to perform")
    instructions: str = Field(..., description="Natural language or structured instruction for the step")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Step-specific parameters (e.g., prompt, tool name, args)")
    # Field to store the execution result of this step
    result: Optional['StepResult'] = Field(None, description="Stores the outcome of the step execution")

# --- Step Result --- Data primarily for StepResultEvent payload ---

class StepErrorDetails(BaseModel):
    kind: str = Field(..., description="Categorical error type (e.g., 'ProviderError', 'ToolExecutionError')")
    detail: str = Field(..., description="Detailed error message or description")

class StepMetrics(BaseModel):
    latency_ms: Optional[float] = Field(None, description="Execution time in milliseconds")
    prompt_tokens: Optional[int] = Field(None, description="Tokens used in prompt (if applicable)")
    completion_tokens: Optional[int] = Field(None, description="Tokens generated in completion (if applicable)")
    cost_usd: Optional[float] = Field(None, description="Estimated cost in USD (if applicable)")

class StepResult(BaseModel):
    step_id: str = Field(..., description="ID matching the originating StepEvent")
    status: Literal["SUCCEEDED", "FAILED", "RETRYING", "CANCELLED"] = Field(..., description="Execution outcome")
    output: Optional[Any] = Field(None, description="Result data from the step execution (can be string, object, etc.)")
    error: Optional[StepErrorDetails] = Field(None, description="Error details if status is FAILED")
    metrics: Optional[StepMetrics] = Field(None, description="Performance metrics for the step execution")

# --- Plan Structure ---

class Plan(BaseModel):
    plan_id: str = Field(..., description="Unique ID for this plan, often related to turn_id")
    turn_id: str # Link back to the turn
    steps: List[Step] = Field(default_factory=list, description="Ordered list of steps in the plan")
    # Could add plan status, generation metadata etc.

# --- Update forward references ---
# Necessary because Turn refers to Plan, and Step refers to StepResult
# which might be defined later in the file or circularly.
Turn.model_rebuild()
Step.model_rebuild()
# Plan.model_rebuild() # Not strictly necessary here as Step doesn't refer back to Plan

# --- Event Envelope (for reference, not strictly a core model but used in events.py) ---
# class EventEnvelope(BaseModel):
#     event_id: str
#     type: str
#     spec_version: str
#     timestamp: datetime
#     trace_id: str
#     tenant_id: Optional[str] = None
#     session_id: Optional[str] = None
#     payload: BaseModel # The specific event payload (TurnEventPayload, StepEventPayload, etc.) 