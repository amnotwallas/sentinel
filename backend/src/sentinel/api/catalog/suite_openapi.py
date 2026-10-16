import json
from functools import cache
from importlib.resources import files
from typing import Any, cast


@cache
def suite_schemas() -> dict[str, Any]:
    resource = files("sentinel.api.catalog").joinpath("suite_schemas.json")
    return cast(dict[str, Any], json.loads(resource.read_text(encoding="utf-8")))
