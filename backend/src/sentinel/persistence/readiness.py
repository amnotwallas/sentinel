"""Read-only schema readiness for the migration assets deployed with this backend."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine


def database_is_current(engine: Engine) -> bool:
    try:
        config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
        config.remove_main_option("prepend_sys_path")
        expected_heads = ScriptDirectory.from_config(config).get_heads()
        if len(expected_heads) != 1:
            return False
        with engine.connect() as connection:
            actual_heads = MigrationContext.configure(connection).get_current_heads()
            return set(actual_heads) == set(expected_heads)
    except Exception:
        return False
