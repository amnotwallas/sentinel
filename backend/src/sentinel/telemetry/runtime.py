import json
import logging
from uuid import UUID

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def provider(service_name: str, endpoint: str | None) -> TracerProvider:
    instance = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if endpoint:
        instance.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=2))
        )
    return instance


def event(name: str, *, job_id: UUID | None = None) -> None:
    # Closed field set: never serialize arbitrary exceptions, settings, or payloads.
    logging.getLogger("sentinel").info(
        json.dumps({"event": name, "job_id": str(job_id) if job_id else None})
    )
