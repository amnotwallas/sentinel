"""Bounded operator/CI smoke run against a running worker; no HTTP test requests."""

import time

from sqlalchemy import select

from sentinel.config import Settings
from sentinel.execution.service import WorkService
from sentinel.persistence.database import create_database
from sentinel.persistence.models import ExecutionRow, JobRow
from sentinel.persistence.queue import PostgresJobStore


def main() -> None:
    settings = Settings()
    engine, sessions = create_database(settings.database_url.get_secret_value())
    try:
        probe = WorkService(PostgresJobStore(sessions)).enqueue_probe()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with sessions() as session:
                state = session.scalar(select(JobRow.state).where(JobRow.id == probe.job_id))
                execution = session.get(ExecutionRow, probe.execution_id)
                if state == "succeeded" and execution and execution.status == "completed":
                    print("Durable probe completed through running worker")
                    return
                if state == "dead":
                    raise SystemExit("probe_failed")
            time.sleep(0.2)  # Bounded operational smoke polling, not a lease test.
        raise SystemExit("probe_timeout")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
