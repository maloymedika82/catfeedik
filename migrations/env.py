"""Alembic migration environment; connection URL comes only from runtime env."""
import os

from alembic import context
from sqlalchemy import create_engine, pool

from backend.db import Base


target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # The PostGIS image provides extension-owned tables outside this app.
    return not (type_ == 'table' and reflected and compare_to is None)


def database_url():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL is required for migrations')
    return url


def run_migrations_offline():
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
