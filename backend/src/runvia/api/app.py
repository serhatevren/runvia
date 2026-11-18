from importlib.metadata import version

from fastapi import FastAPI

from runvia.api import health
from runvia.api.middleware import AccessLogMiddleware, RequestIDMiddleware
from runvia.core.config import Settings, get_settings
from runvia.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings, service="api")

    app = FastAPI(title="Runvia", version=version("runvia"))
    # The last middleware added is the outermost: the request ID is set
    # before the access log runs, so every access line carries it.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    return app
