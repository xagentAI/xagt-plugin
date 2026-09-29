import os
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.action_policy_repository import Base as ActionPolicyBase
from services.funding_service.ledger import Base as FundingBase

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option(
    "sqlalchemy.url",
    os.getenv(
        "CLINK_FUNDING_DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    ),
)
target_metadata = (FundingBase.metadata, ActionPolicyBase.metadata)
version_table = (
    "alembic_version_core"
    if os.getenv("CLINK_NODE_MANAGED") == "1"
    else "alembic_version"
)


def offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        version_table=version_table,
    )
    with context.begin_transaction():
        context.run_migrations()


def online() -> None:
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table=version_table,
        )
        with context.begin_transaction():
            context.run_migrations()


offline() if context.is_offline_mode() else online()
