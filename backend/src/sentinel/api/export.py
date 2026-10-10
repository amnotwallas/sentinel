import argparse
import json
from pathlib import Path

from sentinel.api.app import create_app
from sentinel.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the versioned OpenAPI contract")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(create_app(Settings()).openapi(), indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
