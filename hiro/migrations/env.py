"""Alembic environment.

Two things differ from the generated default:

* the URL comes from the application config, not ``alembic.ini``;
* migrations run under a Postgres advisory lock, because the API and the Celery
  worker both apply migrations on boot and may start at the same moment.
"""

from alembic import context
from sqlalchemy import engine_from_config, pool, text

import hiro.chat.models
import hiro.knowledge_base.models
from hiro.common.logging import configure_logging, get_logger
from hiro.config import get_config
from hiro.db.base import Base

#: Importing these registers their tables on ``Base.metadata``. They are listed
#: here rather than left as bare imports so linters cannot strip them as unused:
#: without them autogenerate sees no models and emits DROP TABLE for everything.
MODEL_MODULES = (hiro.chat.models, hiro.knowledge_base.models)

configure_logging()
logger = get_logger("alembic.env")

config = context.config
target_metadata = Base.metadata
logger.debug(
    "alembic metadata covers %d table(s) from %d module(s): %s",
    len(target_metadata.tables),
    len(MODEL_MODULES),
    ", ".join(sorted(target_metadata.tables)),
)

# Arbitrary but fixed 32-bit key ("baym"), so every process that might migrate
# contends for the same lock.
MIGRATION_LOCK_ID = 0x6261796D


def get_url() -> str:
    return get_config().database.url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (``alembic upgrade --sql``)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Session-level lock: whichever process gets here first migrates, the
        # others block and then find nothing left to do. Committing releases
        # the implicit transaction while keeping the lock held on the session.
        logger.debug("acquiring migration advisory lock")
        connection.execute(
            text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID}
        )
        connection.commit()

        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID}
            )
            connection.commit()
            logger.debug("released migration advisory lock")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
