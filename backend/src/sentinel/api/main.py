import uvicorn
from pydantic import ValidationError

from sentinel.api.app import create_app
from sentinel.config import Settings


def main() -> None:
    try:
        settings = Settings()
    except ValidationError:
        raise SystemExit("invalid_configuration") from None
    uvicorn.run(
        create_app(settings), host=settings.api_host, port=settings.api_port, access_log=False
    )


if __name__ == "__main__":
    main()
