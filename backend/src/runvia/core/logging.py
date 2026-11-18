import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from runvia.core.config import AppEnv, Settings
from runvia.core.request_context import request_id_var

REDACTED = "[REDACTED]"
HANDLER_NAME = "runvia"

# Matched as substrings of lower-cased keys, so `refresh_token` and
# `x_api_key` are caught too. A false positive only hides a value; a false
# negative leaks a credential, so the list errs on the broad side.
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: REDACTED if isinstance(k, str) and _is_sensitive(k) else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(v) for v in value]
    return value


def redact_sensitive_fields(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Safety net for spec §14: callers must not log secrets, this catches mistakes."""
    return {
        key: REDACTED if _is_sensitive(key) else _redact(value) for key, value in event_dict.items()
    }


def add_request_id(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def _add_service(service: str) -> Processor:
    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        event_dict["service"] = service
        return event_dict

    return processor


def configure_logging(settings: Settings, *, service: str) -> None:
    """Route structlog and stdlib (uvicorn, libraries) records through one stdout handler.

    Enrichment runs in the formatter rather than in structlog's own chain, so both
    kinds of record get identical fields, and reconfiguring never leaves cached
    structlog loggers with a stale chain.
    """
    renderer: list[Processor]
    if settings.app_env is AppEnv.DEVELOPMENT:
        renderer = [structlog.dev.ConsoleRenderer()]
    else:
        renderer = [
            # Frame locals are off: they hold raw request data (passwords,
            # tokens) and are added after redaction has run.
            structlog.processors.ExceptionRenderer(
                structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
            ),
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.contextvars.merge_contextvars],
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.stdlib.add_log_level,
            # Reads the logger name from `_record`, so it runs before the meta is removed.
            structlog.stdlib.add_logger_name,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _add_service(service),
            add_request_id,
            redact_sensitive_fields,
            *renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(formatter)

    # Replace only our own handler, so reconfiguring is idempotent and leaves
    # handlers installed by other tools (e.g. pytest's log capture) alone.
    root = logging.getLogger()
    for existing in root.handlers[:]:
        if existing.get_name() == HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Uvicorn installs its own handlers before the app factory runs; hand its
    # records to the root handler instead. Its access log is replaced by
    # AccessLogMiddleware, which has the request ID and timing.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
