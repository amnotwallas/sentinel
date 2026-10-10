import time

from sentinel.config import Settings
from sentinel.worker.main import HEALTH_FILE


def main() -> None:
    try:
        age = time.time() - HEALTH_FILE.stat().st_mtime
    except FileNotFoundError:
        raise SystemExit(1) from None
    raise SystemExit(0 if age < max(5, Settings().heartbeat_seconds * 3) else 1)


if __name__ == "__main__":
    main()
