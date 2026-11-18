import io
import json
import logging
from collections.abc import Callable
from typing import Any

import pytest

from runvia.core.config import AppEnv, Settings
from runvia.core.logging import HANDLER_NAME

type LogReader = Callable[[], list[dict[str, Any]]]


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env=AppEnv.TEST, log_level="INFO")


@pytest.fixture
def read_logs() -> LogReader:
    """Redirect the configured Runvia handler to a buffer; call after configure_logging."""
    buffer = io.StringIO()
    handler = next(h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME)
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(buffer)

    def read() -> list[dict[str, Any]]:
        return [json.loads(line) for line in buffer.getvalue().splitlines()]

    return read
