"""Alembic migration environment (`DB-01`).

`config.get_main_option("sqlalchemy.url")` is always set programmatically
by `trusttable_backend.persistence.database.run_migrations` before this
module runs (`command.upgrade(config, "head")`), so both the offline and
online paths below read the real, current `Settings.database_url` — never
a value duplicated into `alembic.ini` itself.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from trusttable_backend.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers=False`: `fileConfig`'s own default
    # (`True`) would otherwise silently disable every logger that already
    # existed in this process at migration time — including
    # `trusttable_backend.main`'s real production logger
    # (`test_log_safety.py` caught this: running migrations before that
    # test executed silently zeroed its captured log records). Alembic
    # runs embedded inside `main.create_app()`, not as a standalone CLI
    # process where this default would be harmless.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
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
