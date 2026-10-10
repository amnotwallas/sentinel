from typing import Annotated, Literal

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

FieldLocation = Literal["body", "path", "query", "header"]
FieldCode = Literal[
    "required",
    "type_invalid",
    "value_invalid",
    "extra_field",
    "limit_exceeded",
    "duplicate",
    "invalid_uuid",
    "invalid_url",
    "invalid_json_pointer",
    "invalid_secret_reference",
    "secret_placement_forbidden",
    "credential_literal_forbidden",
    "trace_context_forbidden",
    "unsafe_replay_acknowledgement_required",
    "incompatible_fields",
    "cursor_invalid",
]
ProblemCode = Literal[
    "validation_failed",
    "secret_reference_invalid",
    "resource_not_found",
    "revision_conflict",
    "revision_precondition_required",
    "resource_conflict",
    "request_too_large",
    "unsupported_media_type",
    "authentication_required",
    "forbidden_origin",
    "idempotency_conflict",
    "baseline_ineligible",
    "baseline_incompatible",
    "internal_error",
    "http_error",
]


class FieldError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: FieldLocation
    pointer: str
    code: FieldCode
    message: str = Field(min_length=1, max_length=120)


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=120)
    status: int
    code: ProblemCode
    errors: (
        Annotated[list[FieldError], Field(min_length=1, max_length=50)] | SkipJsonSchema[None]
    ) = None


def problem(status: int, code: str, title: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"urn:sentinel:problem:{code}",
            "title": title,
            "status": status,
            "code": code,
        },
    )


def validation_problem(_: RequestValidationError) -> JSONResponse:
    error = _
    errors: list[dict[str, str]] = []
    for item in error.errors()[:50]:
        location, *path = item.get("loc", ("body",))
        location = location if location in {"body", "path", "query", "header"} else "body"
        raw_type = str(item.get("type", ""))
        if raw_type == "missing":
            code = "required"
        elif raw_type == "extra_forbidden":
            code = "extra_field"
            path = ["*"]
        elif raw_type.startswith(("string_type", "int_type", "uuid_type")):
            code = "type_invalid"
        elif "uuid" in raw_type:
            code = "invalid_uuid"
        elif raw_type.startswith(("greater_than", "less_than", "too_")):
            code = "limit_exceeded"
        else:
            code = "value_invalid"
        pointer = "/" + "/".join(
            str(segment).replace("~", "~0").replace("/", "~1") for segment in path
        )
        errors.append(
            {
                "location": str(location),
                "pointer": pointer,
                "code": code,
                "message": code.replace("_", " ").capitalize(),
            }
        )
    errors.sort(key=lambda item: (item["location"], item["pointer"], item["code"]))
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "urn:sentinel:problem:validation_failed",
            "title": "Request validation failed",
            "status": 422,
            "code": "validation_failed",
            "errors": errors,
        },
    )


def field_problem(
    status: int,
    code: str,
    title: str,
    *,
    location: str,
    pointer: str,
    field_code: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"urn:sentinel:problem:{code}",
            "title": title,
            "status": status,
            "code": code,
            "errors": [
                {
                    "location": location,
                    "pointer": pointer,
                    "code": field_code,
                    "message": field_code.replace("_", " ").capitalize(),
                }
            ],
        },
    )
