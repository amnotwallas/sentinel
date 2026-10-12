"""Verify generated contracts in temporary files without rewriting the checkout."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    frontend = root / "frontend"
    tools = frontend / "node_modules" / ".bin"
    if not all((tools / tool).exists() for tool in ("prettier", "openapi-typescript")):
        print("Missing frontend tools; run make setup.", file=sys.stderr)
        return 2

    # Contract output must not depend on an operator's runtime configuration or secrets.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("SENTINEL_")
    }
    with TemporaryDirectory(prefix="sentinel-contract-") as directory:
        output = Path(directory)
        spec = output / "openapi.json"
        schema = output / "schema.ts"
        # Multi-API Redocly configs override CLI output paths. Use an isolated config.
        redocly = output / "redocly.yaml"
        redocly.write_text("{}\n")
        subprocess.run(
            [sys.executable, "-m", "sentinel.api.export", str(spec)],
            cwd=root,
            env=environment,
            check=True,
        )
        formatted = subprocess.run(
            [
                "node",
                str(tools / "prettier"),
                "--config",
                str(frontend / ".prettierrc.json"),
                str(spec),
            ],
            cwd=frontend,
            env=environment,
            stdout=subprocess.PIPE,
            check=True,
        )
        spec.write_bytes(formatted.stdout)
        subprocess.run(
            [
                "node",
                str(tools / "openapi-typescript"),
                str(spec),
                "-o",
                str(schema),
                "--redocly",
                str(redocly),
            ],
            cwd=output,
            env=environment,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        drift = False
        for generated, committed in (
            (spec, frontend / "openapi.json"),
            (schema, frontend / "src/shared/api/generated/schema.ts"),
        ):
            if not committed.exists() or generated.read_bytes() != committed.read_bytes():
                print(f"Contract drift: {committed.relative_to(root)}", file=sys.stderr)
                drift = True
        if drift:
            return 1
    print("OpenAPI and generated TypeScript match; checkout artifacts were not rewritten.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    except FileNotFoundError:
        print("Missing input or executable; run make setup and check Node/Python.", file=sys.stderr)
        raise SystemExit(2) from None
