"""Read-only schema readiness for the migration assets deployed with this backend."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine


def database_is_current(engine: Engine) -> bool:
    try:
        # Resolve deployment assets independently of the process working directory.
        config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
        # CLI path bootstrapping would mutate global sys.path on each threaded probe.
        # The API already runs from the installed package; readiness only reads assets.
        config.remove_main_option("prepend_sys_path")
        expected_heads = ScriptDirectory.from_config(config).get_heads()
        # Sentinel maintains one linear migration chain; ambiguous assets fail closed.
        if len(expected_heads) != 1:
            return False
        with engine.connect() as connection:
            actual_heads = MigrationContext.configure(connection).get_current_heads()
            return set(actual_heads) == set(expected_heads)
    except Exception:
        # Health responses/logs must not expose DSNs, SQL or filesystem exceptions.
        return False
