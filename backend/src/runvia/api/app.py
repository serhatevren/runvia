from importlib.metadata import version

from fastapi import FastAPI

from runvia.api import health
from runvia.api.middleware import RequestIDMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="Runvia", version=version("runvia"))
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    return app
