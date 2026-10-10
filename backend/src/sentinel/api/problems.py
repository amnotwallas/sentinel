from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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
    return problem(422, "validation_failed", "Request validation failed")
