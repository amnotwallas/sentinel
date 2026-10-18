from pathlib import Path

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


def test_target_ca_bundle_requires_absolute_valid_pem(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pem"
    invalid.write_text("not-a-certificate", encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings(target_ca_bundle=str(invalid))
    with pytest.raises(ValidationError):
        Settings(target_ca_bundle="relative.pem")


def test_target_ca_bundle_path_is_not_in_settings_repr() -> None:
    settings = Settings(target_ca_bundle=None)
    assert "target_ca_bundle" not in repr(settings)
