import json
from functools import cache
from importlib.resources import files
from typing import Any, cast


@cache
def catalog_schemas() -> dict[str, Any]:
    resource = files("sentinel.api.catalog").joinpath("catalog_schemas.json")
    return cast(dict[str, Any], json.loads(resource.read_text(encoding="utf-8")))
