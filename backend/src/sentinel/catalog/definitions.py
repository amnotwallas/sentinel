from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


class DefinitionValidationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TestDefinition:
    document: Mapping[str, object]
    policy_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "document", cast(Mapping[str, object], _freeze(self.document)))

    def to_document(self) -> dict[str, object]:
        return cast(dict[str, object], _thaw(self.document))
