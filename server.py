from fastapi import FastAPI, WebSocket, Request, HTTPException
from pathlib import Path
# Correct imports relative to project root
# from agent_shell.core.registry import Registry # Incorrect
# from agent_shell.core.runtime import Runtime   # Incorrect
# from agent_shell.core.schema import Turn       # Incorrect
from contextlib import asynccontextmanager
import asyncio
import logging
from dotenv import load_dotenv
from typing import Optional
import uvicorn
from fastapi.responses import JSONResponse
from core.logging_config import configure_logging
import structlog
import uuid
import time
from prometheus_fastapi_instrumentator import Instrumentator, metrics as pfi_metrics_module
from prometheus_fastapi_instrumentator.metrics import Info
from prometheus_client import Counter, Histogram, Summary, Gauge
from core.metrics import LLM_REQUEST_LATENCY, LLM_TOKENS_TOTAL, LLM_COST_TOTAL, LLM_ERRORS_TOTAL, ACTIVE_TURNS

# KFM Core Imports
from core.config import AppConfig
from core.events import EventPublisherSubscriber, EventEnvelope, TurnEventPayload, StepEventPayload, StepResultEventPayload, event_publisher, shutdown_event, start_event_workers, stop_event_workers
from core.runtime import TurnManager, PlanExecutor, StepProcessor
from core.context import ContextManager
from providers.factory import ProviderFactory
from core.personality import PersonalityPackManager
from memory.redis_cache import RedisCacheService
from memory.lancedb_store import LanceDBVectorStore
from memory.manager import MemoryManager, memory_lifespan
from core.models import Message # MODIFIED: Changed from core.messaging.message

# Load environment variables from .env file
load_dotenv()

# Remove initial standard logger setup
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# --- Global Configuration ---
try:
    app_config = AppConfig()
    # If load_config includes logging, it might use standard logging before structlog is set up.
    # Consider configuring a basic standard logger first if early logs are critical.
except Exception as e:
    # Use standard logging here because structlog isn't configured yet
    logging.basicConfig() # Ensure basic config exists for the next line
    logging.getLogger(__name__).critical(f"Failed to load configuration: {e}", exc_info=True)
    raise # Re-raise the exception to stop the application

# --- Configure Logging ---
# Now structlog can be configured, potentially using values from app_config
configure_logging(log_level=app_config.log_level, force_json=app_config.log_json)
log = structlog.get_logger(__name__) # Define structlog logger here

# --- Worker Functions (REMOVED - Now in core/events.py) ---
# async def step_event_worker(...): ...
# async def step_result_event_worker(...): ...

# --- FastAPI Lifecycle (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and shutdown processes."""
    # Lifespan starts before structlog is configured IF logging happens here.
    # Best practice: configure structlog EARLIER if possible, or use standard logging for earliest lifespan messages.
    # For now, assuming structlog is configured by the time most lifespan logging occurs.
    log.info("Application startup...") # Use log
    
    # Config loading happens globally now, before lifespan
    # Use app_config directly
    log.info(f"Using loaded configuration. Log level set to {app_config.log_level.upper()}") # Use log

    # Service initialization logging (using log)
    provider_factory = ProviderFactory(app_config)
    personality_manager = PersonalityPackManager(app_config.personality)
    log.info("Core services initialized (ProviderFactory, PersonalityManager).")

    # Use memory_lifespan context manager for memory services
    async with memory_lifespan(app_config) as memory_state:
        app.state.memory_manager = memory_state.memory_manager
        log.info("Memory services initialized via memory_lifespan.")

        # Initialize ContextManager *after* MemoryManager
        context_manager = ContextManager(memory_manager=app.state.memory_manager)
        log.info("ContextManager initialized.")

        # Initialize Runtime Components (Inject dependencies)
        plan_executor = PlanExecutor(
            provider_factory=provider_factory,
            event_publisher=event_publisher,
            personality_manager=personality_manager,
            memory_manager=app.state.memory_manager
        )
        step_processor = StepProcessor(
            app_config=app_config,
            provider_factory=provider_factory,
            context_manager=context_manager, 
            event_publisher=event_publisher,
            personality_manager=personality_manager,
            memory_manager=app.state.memory_manager 
        )
        # Pass event_publisher to TurnManager
        turn_manager = TurnManager(
            app_config=app_config, # Pass AppConfig here
            plan_executor=plan_executor, 
            context_manager=context_manager, 
            event_publisher=event_publisher, # Pass the global publisher
            personality_manager=personality_manager
        )
        log.info("Runtime components initialized (PlanExecutor, StepProcessor, TurnManager).")

        # Store services/config on app.state for access by endpoints/middleware
        app.state.config = app_config
        app.state.context_manager = context_manager
        app.state.provider_factory = provider_factory
        app.state.personality_manager = personality_manager
        app.state.plan_executor = plan_executor
        app.state.step_processor = step_processor
        app.state.turn_manager = turn_manager
        log.info("Services attached to app.state.")

        # Start Background Worker Tasks using global queue and injected components
        log.info("Starting event queue workers...") # Use log
        # Call start_event_workers from core.events
        worker_tasks = start_event_workers(
            publisher=event_publisher, 
            turn_manager=turn_manager, 
            step_processor=step_processor,
            shutdown_event_flag=shutdown_event,
            num_step_event_workers=app_config.event_queue_max_size // 500, # Example: scale workers slightly with queue size
            num_step_result_event_workers=app_config.event_queue_max_size // 500 # Example
        )
        log.info(f"{len(worker_tasks)} event workers started.") # Use log

        log.info("Application startup complete.") # Use log

        try:
            yield # Application runs here
        finally:
            # --- Shutdown Process --- (Replace logger.* with log.*)
            log.info("Shutting down application...") # Use log

            # 1. Stop Background Worker Tasks
            log.info("Stopping event worker tasks...") # Use log
            # Call stop_event_workers from core.events
            await stop_event_workers(worker_tasks, shutdown_event)
            log.info("Event worker tasks stopped.") # Use log
            # except asyncio.CancelledError: # Caught within stop_event_workers now
            #     log.info("Event worker tasks cancelled during shutdown.") # Use log

            # 2. Close Services and Connections (memory manager closed by its lifespan)
            log.info("Closing connections...") # Use log
            if hasattr(app.state, 'provider_factory') and app.state.provider_factory:
                 await app.state.provider_factory.close_all()
            # Close other resources if needed

            log.info("Application shutdown complete.") # Use log

app = FastAPI(title="Kernel Function Machine Framework", description="An extensible framework...", version="0.1.0", lifespan=lifespan)

# Instrument the app with more detailed Prometheus metrics
instrumentator = Instrumentator(
    should_group_status_codes=False, # Example: retain original status codes
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/metrics"], # Exclude metrics endpoint itself
    # Other general Instrumentator settings if needed
)

# Add predefined metrics to this instance
# For http_request_duration_seconds (latency)
instrumentator.add(pfi_metrics_module.latency(
    metric_name="http_request_duration_seconds", 
    metric_doc="API call duration in seconds",
    should_include_handler=True, 
    should_include_method=True,
    should_include_status=True,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, float("inf")), # Example buckets
))

# For http_requests_total (counter)
instrumentator.add(pfi_metrics_module.requests(
    metric_name="http_requests_total",
    metric_doc="Total HTTP requests processed",
    should_include_handler=True,
    should_include_method=True,
    should_include_status=True,
))

instrumentator.instrument(app) # Instrument the app AFTER adding all metric definitions

# Configure custom labels and tag KFM-specific endpoints
# REMOVED @instrumentator.instrumentation decorator and customize_metrics function
# @instrumentator.instrumentation
# def customize_metrics(info: Info):
#     if info.request:
#         # Add custom labels based on endpoint characteristics
#         if info.request.url.path.startswith("/v1/"):
#             info.labels.update({"api_version": "v1"})

# Expose combined metrics endpoint with all custom metrics
instrumentator.expose(app, endpoint="/metrics", include_in_schema=True, tags=["observability"])

# Add custom metrics for request tracking
@app.middleware("http")
async def track_metrics_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4())) # Generate if missing
    
    # Add contextual information to logs
    structlog.contextvars.bind_contextvars(
        path=request.url.path,
        method=request.method,
        client_host=request.client.host,
        client_port=request.client.port,
        request_id=request_id,
        trace_id=request_id  # Use request_id as trace_id for consistent tracing
    )
    
    log.info("Received request")
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = (time.time() - start_time) * 1000
    structlog.contextvars.bind_contextvars(
        status_code=response.status_code, 
        process_time_ms=round(process_time, 2)
    )
    log.info("Sending response")
    
    # Add request ID to response header for client-side tracing
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Trace-ID"] = request_id
    
    structlog.contextvars.clear_contextvars()
    return response

# Define API endpoints (Replace logger.* with log.*)

@app.websocket("/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    turn_manager: Optional[TurnManager] = getattr(ws.app.state, 'turn_manager', None)
    if not turn_manager:
        # Use standard logging here as structlog might not be fully configured? Or try log?
        # logging.getLogger(__name__).error(...) # Safer fallback
        await ws.close(code=1011, reason="Server configuration error: TurnManager not available.")
        log.error("TurnManager not found in app state during /chat request.") # Try log
        return

    try:
        while True:
            user_text = await ws.receive_text()
            log.info(f"Received message via WebSocket", user_text=user_text) # Use log
            
            # TODO: This Turn object doesn't match the one used by TurnManager
            # Need to adapt this endpoint to create a TurnEventPayload
            # initial_turn = Turn(user_input=user_text)
            # await turn_manager.start_turn(initial_turn)
            
            # Simulate creating a TurnEventPayload
            turn_id = f"ws_turn_{uuid.uuid4()}"
            trace_id = f"ws_trace_{uuid.uuid4()}"
            session_id = None # TODO: How to get session ID for websocket?
            payload = {"message": user_text} # Simple payload
            event_payload = TurnEventPayload(
                turn_id=turn_id, 
                input_data=payload,
                session_id=session_id,
                trace_id=trace_id
            )
            event = EventEnvelope(event_type="TURN_START", payload=event_payload)
            await event_publisher.publish(event)
            log.info("Websocket initiated turn start event", turn_id=turn_id)

            await ws.send_text(f"Acknowledged: '{user_text}'. Processing started (Turn ID: {turn_id}). Streaming TBD.")

    except Exception as e:
        log.error(f"Error in WebSocket chat: {e}", exc_info=True) # Use log
        try:
            await ws.close(code=1011, reason=f"Server error: {e}")
        except: pass

# --- Management Endpoints --- (Replace logger.* with log.*)

@app.post("/management/reload/personalities", status_code=200)
async def reload_personalities_endpoint(request: Request):
    """API endpoint to trigger reloading of personality packs."""
    log.info("Received request to reload personality packs.") # Use log
    try:
        manager: Optional[PersonalityPackManager] = getattr(request.app.state, 'personality_manager', None)
        if manager:
            await manager.reload_packs()
            count = len(manager.list_packs())
            log.info(f"Successfully reloaded {count} personality packs.") # Use log
            return {"message": f"Successfully reloaded {count} personality packs."}
        else:
            log.error("PersonalityPackManager not found in app state during reload request.") # Use log
            raise HTTPException(status_code=500, detail="Personality manager not initialized.")
    except Exception as e:
        log.exception("Error reloading personality packs via API.") # Use log
        raise HTTPException(status_code=500, detail=f"Failed to reload personalities: {e}")

# --- Middleware (Example: Logging requests) --- (Replace logger.* with log.*)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4())) # Generate if missing
    structlog.contextvars.bind_contextvars(
        path=request.url.path,
        method=request.method,
        client_host=request.client.host,
        client_port=request.client.port,
        request_id=request_id 
    )
    log.info("Received request") # Use log
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = (time.time() - start_time) * 1000
    structlog.contextvars.bind_contextvars(status_code=response.status_code, process_time_ms=round(process_time, 2))
    log.info("Sending response") # Use log
    structlog.contextvars.clear_contextvars()
    response.headers["X-Request-ID"] = request_id # Add request ID to response header
    return response

# --- API Endpoints --- (Replace logger.* with log.*)

# Example endpoint to trigger a turn
@app.post("/v1/turns", status_code=202) # 202 Accepted
async def create_turn(request: Request):
    """Accepts a request to start a new agent turn."""
    try:
        payload = await request.json()
    except Exception as e:
        log.error("Invalid JSON payload received for /v1/turns", error=str(e))
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    # Extract data for TurnEventPayload
    user_message_data = payload.get("user_message")
    if not isinstance(user_message_data, dict) or \
       not user_message_data.get("role") or not user_message_data.get("content"):
        log.warning("Missing or malformed 'user_message' in /v1/turns request", payload=payload)
        raise HTTPException(status_code=422, detail="'user_message' (with role and content) is required.")
    
    try:
        user_message_obj = Message(**user_message_data)
    except Exception as e:
        log.warning("Failed to parse 'user_message' object", error=str(e), data=user_message_data)
        raise HTTPException(status_code=422, detail=f"Invalid 'user_message' structure: {e}")

    personality_id = payload.get("personality_id")
    if not personality_id or not isinstance(personality_id, str):
        log.warning("Missing or invalid 'personality_id' in /v1/turns request", payload=payload)
        raise HTTPException(status_code=422, detail="'personality_id' (string) is required.")

    session_id = payload.get("session_id") # Optional
    if session_id and not isinstance(session_id, str):
        log.warning("Invalid 'session_id' (must be string) in /v1/turns request", payload=payload)
        raise HTTPException(status_code=422, detail="Invalid 'session_id', must be a string if provided.")
        
    metadata = payload.get("metadata") # Optional
    if metadata and not isinstance(metadata, dict):
        log.warning("Invalid 'metadata' (must be dict) in /v1/turns request", payload=payload)
        raise HTTPException(status_code=422, detail="Invalid 'metadata', must be a dictionary if provided.")

    turn_id = payload.get("turn_id", f"turn_{uuid.uuid4()}") # Allow client-provided or generate
    trace_id = request.headers.get("x-request-id") or f"trace_{uuid.uuid4()}" 

    log.info("Received request to start turn via POST", turn_id=turn_id, trace_id=trace_id, personality_id=personality_id)

    try:
        # Create TurnEventPayload using specific fields
        event_payload = TurnEventPayload(
            turn_id=turn_id, 
            user_message=user_message_obj,
            personality_id=personality_id,
            metadata=metadata, # Will be None if not provided
            # instructions and parameters are now optional in TurnEventPayload
            # Remove placeholders
        )
        event = EventEnvelope(
            event_id=f"evt_{uuid.uuid4()}", # Ensure event_id is unique
            type="TURN_START", # Consistent event type string
            spec_version="1.0.0", # Example spec version
            trace_id=trace_id,
            session_id=session_id, # Pass session_id to envelope
            payload=event_payload
        )
        await event_publisher.publish(event)
        log.info("Turn start event queued", turn_id=turn_id, event_type=event.type)
        return JSONResponse(
            content={"message": "Turn processing initiated", "turn_id": turn_id, "trace_id": trace_id},
            status_code=202
        )
    except HTTPException: # Re-raise HTTPExceptions from parsing
        raise
    except Exception as e:
        log.exception("Failed to queue turn start event", turn_id=turn_id)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

# Placeholder for getting turn status
@app.get("/v1/turns/{turn_id}")
async def get_turn_status(request: Request, turn_id: str):
    context_manager: ContextManager = request.app.state.context_manager
    log.info("Request received for turn status", turn_id=turn_id)
    
    turn_context = await context_manager.get_turn(turn_id)
    
    if not turn_context:
        log.warning("Turn state not found for /v1/turns/{turn_id}", turn_id=turn_id)
        # Let FastAPI handle this directly. It will return a 404 response.
        raise HTTPException(status_code=404, detail="Turn not found") 
    
    # If turn_context exists, proceed to return 200. Catch errors during serialization.
    try:
        # Assuming status is an Enum and other fields might need processing or dumping
        response_payload = {
            "turn_id": turn_context.turn_id,
            "status": turn_context.status.value if hasattr(turn_context.status, 'value') else str(turn_context.status),
            "user_message": turn_context.user_message.model_dump() if turn_context.user_message else None,
            "final_response": turn_context.final_response.model_dump() if turn_context.final_response else None,
            "created_at": turn_context.created_at.isoformat() if turn_context.created_at else None,
            "updated_at": turn_context.updated_at.isoformat() if turn_context.updated_at else None,
            "session_id": turn_context.session_id,
            "metadata": turn_context.metadata,
            "metrics": turn_context.metrics,
            "plan": turn_context.plan.model_dump() if turn_context.plan else None # Added plan
        }
        return JSONResponse(content=response_payload)
    except Exception as e:
        # This catch is now only for errors during serialization of a found turn_context
        log.error("Error serializing turn context for /v1/turns/{turn_id}", turn_id=turn_id, exception=str(e), exc_info=True)
        # It's crucial to raise an HTTPException here, otherwise FastAPI might default to 500 for unhandled exceptions.
        raise HTTPException(status_code=500, detail=f"Internal server error while processing turn data: {str(e)}")

# --- Health Check Endpoint --- (Replace logger.* with log.*)
@app.get("/health", status_code=200)
async def health_check():
    log.debug("Health check requested.") # Use log
    # TODO: Add checks for dependencies (e.g., redis ping, lancedb connection?)
    return {"status": "ok"}

# --- Main Execution Block --- (Replace logger.* with log.*)
if __name__ == "__main__":
    # Config loading & structlog configuration happen globally above
    
    # Pass message as first arg, context as kwargs for structlog
    log.info("Starting KFM server", host=app_config.host, port=app_config.port, reload=app_config.reload) # Use log
    uvicorn.run(
        "server:app", 
        host=app_config.host, 
        port=app_config.port, 
        reload=app_config.reload,
        log_config=None # Disable uvicorn default logging
    )
    log.info("KFM server stopped") # Use log