"""Alembic environment for explicit Hosted Facilitator migrations."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config
target_metadata = None


def _database_url() -> str:
    value = (
        config.attributes.get("database_url")
        or os.environ.get("ALEMBIC_DATABASE_URL")
        or os.environ.get("CLINK_HOSTED_POSTGRES_URL")
        or config.get_main_option("sqlalchemy.url")
    )
    if not isinstance(value, str) or not value.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        raise RuntimeError("Alembic PostgreSQL URL is required")
    return value


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    injected = config.attributes.get("connection")
    if injected is not None:
        if callable(getattr(injected, "connect", None)):
            with injected.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
        else:
            context.configure(connection=injected, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        return

    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
