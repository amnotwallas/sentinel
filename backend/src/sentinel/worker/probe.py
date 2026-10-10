import json

from sentinel.config import Settings
from sentinel.execution.service import WorkService
from sentinel.persistence.database import create_database
from sentinel.persistence.queue import PostgresJobStore


def main() -> None:
    """Operator smoke helper only; no product API endpoint or target HTTP execution."""
    settings = Settings()
    engine, sessions = create_database(settings.database_url.get_secret_value())
    try:
        result = WorkService(
            PostgresJobStore(sessions), max_deliveries=settings.max_deliveries
        ).enqueue_probe()
        print(json.dumps({"execution_id": str(result.execution_id), "job_id": str(result.job_id)}))
    finally:
        engine.dispose()
