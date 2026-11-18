import pytest
from pydantic import ValidationError

from runvia.core.config import AppEnv, Settings


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    settings = Settings()

    assert settings.app_env is AppEnv.PRODUCTION
    assert settings.log_level == "WARNING"


def test_fails_fast_without_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(ValidationError, match="app_env"):
        Settings()


@pytest.mark.parametrize(("name", "value"), [("APP_ENV", "prod"), ("LOG_LEVEL", "VERBOSE")])
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()
