"""Prometheus metrics for the KFM Framework."""

import time
from typing import Dict, Optional, Any
from prometheus_client import Counter, Histogram, Gauge
import structlog

log = structlog.get_logger(__name__)

# Define metrics as module-level variables
# Use same metrics names as specified in requirements

# Latency metrics
LLM_REQUEST_LATENCY = Histogram(
    'llm_request_latency_seconds', 
    'Latency of LLM API requests in seconds',
    ['provider', 'model', 'status']
)

# Token count metrics
LLM_TOKENS_TOTAL = Counter(
    'llm_tokens_total',
    'Total number of tokens processed by LLMs',
    ['provider', 'model', 'type']  # type can be 'prompt', 'completion', or 'embedding'
)

# Cost metrics (in USD)
LLM_COST_TOTAL = Counter(
    'llm_cost_total_usd',
    'Total cost of LLM API calls in USD',
    ['provider', 'model', 'type']  # type can be 'prompt', 'completion', 'embedding', or 'total'
)

# Error metrics
LLM_ERRORS_TOTAL = Counter(
    'llm_errors_total',
    'Total number of errors from LLM providers',
    ['provider', 'model', 'error_type']  # error_type can be 'auth', 'rate_limit', 'bad_request', 'api', etc.
)

# Step metrics
STEP_EXECUTION_TOTAL = Counter(
    'step_execution_total',
    'Total number of steps executed',
    ['step_type', 'status']  # step_type can be 'LLM_CALL', 'TOOL_CALL', 'MEMORY_OP', etc.
)

# Turn metrics
TURN_EXECUTION_TOTAL = Counter(
    'turn_execution_total',
    'Total number of turns executed',
    ['status']  # status can be 'SUCCEEDED', 'FAILED', etc.
)

# Current active turns gauge
ACTIVE_TURNS = Gauge(
    'active_turns',
    'Number of currently active turns'
)

# Helper functions for tracking metrics

def record_llm_request(
    provider: str,
    model: str,
    start_time: float,
    end_time: float,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    status: str = "success",
    error_type: Optional[str] = None
) -> None:
    """
    Record metrics for an LLM API request.
    
    Args:
        provider: The LLM provider (e.g., 'openai', 'anthropic')
        model: The model used (e.g., 'gpt-4o', 'claude-3-opus')
        start_time: Request start time (time.time())
        end_time: Request end time (time.time())
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
        cost: Total cost in USD
        status: Request status ('success' or 'error')
        error_type: Type of error if status is 'error'
    """
    duration = end_time - start_time
    
    # Record latency
    LLM_REQUEST_LATENCY.labels(provider=provider, model=model, status=status).observe(duration)
    
    # Record token counts
    if input_tokens > 0:
        LLM_TOKENS_TOTAL.labels(provider=provider, model=model, type='prompt').inc(input_tokens)
    if output_tokens > 0:
        LLM_TOKENS_TOTAL.labels(provider=provider, model=model, type='completion').inc(output_tokens)
    
    # Record cost
    if cost > 0:
        LLM_COST_TOTAL.labels(provider=provider, model=model, type='total').inc(cost)
    
    # Record errors if any
    if status == 'error' and error_type:
        LLM_ERRORS_TOTAL.labels(provider=provider, model=model, error_type=error_type).inc()

def record_embedding_request(
    provider: str,
    model: str,
    start_time: float,
    end_time: float,
    input_tokens: int,
    cost: float,
    status: str = "success",
    error_type: Optional[str] = None
) -> None:
    """
    Record metrics for an embedding API request.
    
    Args:
        provider: The embedding provider (e.g., 'openai')
        model: The model used (e.g., 'text-embedding-ada-002')
        start_time: Request start time (time.time())
        end_time: Request end time (time.time())
        input_tokens: Number of input tokens
        cost: Total cost in USD
        status: Request status ('success' or 'error')
        error_type: Type of error if status is 'error'
    """
    duration = end_time - start_time
    
    # Record latency
    LLM_REQUEST_LATENCY.labels(provider=provider, model=model, status=status).observe(duration)
    
    # Record token counts
    if input_tokens > 0:
        LLM_TOKENS_TOTAL.labels(provider=provider, model=model, type='embedding').inc(input_tokens)
    
    # Record cost
    if cost > 0:
        LLM_COST_TOTAL.labels(provider=provider, model=model, type='embedding').inc(cost)
    
    # Record errors if any
    if status == 'error' and error_type:
        LLM_ERRORS_TOTAL.labels(provider=provider, model=model, error_type=error_type).inc()

def record_step_execution(step_type: str, status: str) -> None:
    """
    Record metrics for a step execution.
    
    Args:
        step_type: Type of step (e.g., 'LLM_CALL', 'TOOL_CALL', 'MEMORY_OP')
        status: Execution status ('SUCCEEDED' or 'FAILED')
    """
    STEP_EXECUTION_TOTAL.labels(step_type=step_type, status=status).inc()

def record_turn_started() -> None:
    """Record that a new turn has started."""
    ACTIVE_TURNS.inc()

def record_turn_completed(status: str) -> None:
    """
    Record that a turn has completed.
    
    Args:
        status: Completion status ('SUCCEEDED' or 'FAILED')
    """
    ACTIVE_TURNS.dec()
    TURN_EXECUTION_TOTAL.labels(status=status).inc() 