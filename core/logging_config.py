import logging
import sys
import structlog
import uuid

def configure_logging(log_level: str = "INFO", force_json: bool = False):
    """
    Configures structlog and standard library logging.

    Args:
        log_level: The minimum log level to output (e.g., "INFO", "DEBUG").
        force_json: If True, always use JSONRenderer. Otherwise, uses ConsoleRenderer
                    if sys.stdout.isatty() and not force_json.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,
        structlog.contextvars.merge_contextvars,
    ]

    # Custom processor to add trace_id if not present
    def add_trace_id(logger, method_name, event_dict):
        """Ensure all logs have a trace_id for correlation."""
        if "trace_id" not in event_dict:
            event_dict["trace_id"] = str(uuid.uuid4())
        return event_dict

    # Add our custom processor to the shared processors
    shared_processors.append(add_trace_id)

    is_tty = sys.stdout.isatty()
    if force_json or not is_tty:
        final_processor = structlog.processors.JSONRenderer()
    else:
        final_processor = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Instantiate ProcessorFormatter directly
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=final_processor,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    if not root_logger.hasHandlers():
        root_logger.addHandler(handler)
    
    try:
        numeric_level = getattr(logging, log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError(f"Invalid log level: {log_level}")
        root_logger.setLevel(numeric_level)
    except ValueError as e:
        root_logger.setLevel(logging.INFO)
        # Use a temporary logger for this one-off warning
        temp_logger_name = "logging_config_warning"
        temp_logger = logging.getLogger(temp_logger_name)
        
        # Check if handlers are already added to avoid duplication during tests or reloads
        if not any(h.name == f"{temp_logger_name}_stderr_handler" for h in temp_logger.handlers):
            temp_handler = logging.StreamHandler(sys.stderr)
            temp_handler.name = f"{temp_logger_name}_stderr_handler" # Name handler for identification
            temp_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            temp_handler.setFormatter(temp_formatter)
            temp_logger.addHandler(temp_handler)
            temp_logger.setLevel(logging.WARNING)
            temp_logger.propagate = False # Prevent double logging with root
            temp_logger.warning(f"Invalid LOG_LEVEL '{log_level}'. Defaulting to INFO. Error: {e}")
            # No need to remove handler here if we use propagate=False and check for existing handlers

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("renderer_type", nargs="?", default="console", choices=["console", "json"],
                        help="Type of renderer to use ('console' or 'json')")
    parser.add_argument("--level", default="INFO", help="Log level (e.g., DEBUG, INFO, WARNING)")
    args = parser.parse_args()
    
    force_json_output = args.renderer_type == "json"
    
    print(f"Configuring logging with level: {args.level}, force_json: {force_json_output}, is_tty: {sys.stdout.isatty()}")
    configure_logging(log_level=args.level, force_json=force_json_output)
    
    log = structlog.get_logger("example_logger")
    log.debug("This is a debug message.", data={"key": "value"})
    log.info("This is an info message.", user_id=123, action="login")
    log.warning("This is a warning.", details="Something might be wrong.")
    log.error("This is an error.", error_code=500, path="/test")
    try:
        1/0
    except ZeroDivisionError:
        log.exception("An exception occurred!")

    std_lib_logger = logging.getLogger("std_lib_example")
    std_lib_logger.info("Info from standard library logger")
    std_lib_logger.warning("Warning from standard library logger %s", "with args") 