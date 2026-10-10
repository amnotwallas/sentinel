import pytest
from pydantic import SecretStr, ValidationError

from sentinel.config import Settings


def test_remote_bind_requires_token() -> None:
    with pytest.raises(ValidationError):
        Settings(api_host="0.0.0.0", api_token=None)


def test_heartbeat_cannot_outlive_lease() -> None:
    with pytest.raises(ValidationError):
        Settings(lease_seconds=30, heartbeat_seconds=30)


def test_database_requires_postgresql() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=SecretStr("sqlite:///:memory:"))


def test_settings_repr_hides_credentials() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://user:canary-password@localhost/test"),
        api_token=SecretStr("canary-token"),
    )
    assert "canary" not in repr(settings)
