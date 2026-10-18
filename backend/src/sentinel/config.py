import ssl
from ipaddress import ip_address
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTINEL_", extra="ignore")

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://sentinel:sentinel-local-only@127.0.0.1:5432/sentinel"
    )
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_token: SecretStr | None = None
    lease_seconds: int = Field(default=60, ge=5, le=300)
    heartbeat_seconds: float = Field(default=15, ge=0.1, le=60)
    max_deliveries: int = Field(default=3, ge=1, le=3)
    poll_seconds: float = Field(default=1, ge=0.05, le=1)
    tempo_url: str = "http://127.0.0.1:3200"
    otlp_endpoint: str | None = None
    target_ca_bundle: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_safety(self) -> Self:
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use postgresql+psycopg")
        try:
            local = ip_address(self.api_host).is_loopback
        except ValueError:
            local = self.api_host == "localhost"
        if not local and (self.api_token is None or not self.api_token.get_secret_value()):
            raise ValueError("non-loopback API binding requires api_token")
        if self.heartbeat_seconds >= self.lease_seconds / 2:
            raise ValueError("heartbeat must be less than half the lease duration")
        if self.target_ca_bundle is not None:
            path = Path(self.target_ca_bundle)
            if not path.is_absolute():
                raise ValueError("target_ca_bundle must be an absolute path")
            try:
                ssl.create_default_context().load_verify_locations(cafile=path)
            except (OSError, ssl.SSLError):
                raise ValueError("target_ca_bundle_invalid") from None
        return self
