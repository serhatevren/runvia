from enum import StrEnum
from functools import cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    # Values come only from the process environment. Runners inject `.env`
    # (Compose `env_file`, `uvicorn --env-file`), so tests and containers never
    # pick up a stray file from the working directory.
    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    app_env: AppEnv
    log_level: LogLevel = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


@cache
def get_settings() -> Settings:
    return Settings()
