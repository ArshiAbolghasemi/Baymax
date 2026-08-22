"""Database configuration."""

from dynaconf import Dynaconf, Validator

from hiro.common.env import dynaconf_kwargs


class DatabaseConfig(Dynaconf):
    """Postgres connection and pool settings.

    Properties coerce explicitly rather than trusting the environment's string
    values to arrive as the right type.
    """

    def __init__(self) -> None:
        super().__init__(
            **dynaconf_kwargs([Validator("DATABASE_URL", must_exist=True, is_type_of=str)])
        )

    @property
    def url(self) -> str:
        """SQLAlchemy URL.

        A bare ``postgresql://`` scheme is upgraded to ``postgresql+psycopg://``:
        SQLAlchemy would otherwise reach for psycopg2, which this project does
        not install. Normalising here means one DATABASE_URL works for psql,
        Alembic and the app alike.
        """
        url = str(self.get("DATABASE_URL"))
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        return url

    @property
    def pool_size(self) -> int:
        return int(self.get("DATABASE_POOL_SIZE", 5))

    @property
    def max_overflow(self) -> int:
        return int(self.get("DATABASE_MAX_OVERFLOW", 10))

    @property
    def pool_pre_ping(self) -> bool:
        return bool(self.get("DATABASE_POOL_PRE_PING", True))

    @property
    def echo(self) -> bool:
        return bool(self.get("DATABASE_ECHO", False))
