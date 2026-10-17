"""Isolated runtime secret resolution ports.

The resolver is intentionally tiny: catalog and persistence code never depend on
process state, and callers receive a value only while constructing an in-memory
request.
"""

import os
from collections.abc import Mapping
from typing import Protocol


class SecretNotFound(LookupError):
    """A referenced operator-managed secret is not available."""


class SecretResolver(Protocol):
    def resolve(self, name: str) -> str: ...


class EnvironmentSecretResolver:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def resolve(self, name: str) -> str:
        value = self._environ.get(f"SENTINEL_SECRET_{name}")
        if value is None or value == "":
            raise SecretNotFound(name)
        return value
