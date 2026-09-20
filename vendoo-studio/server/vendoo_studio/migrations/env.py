"""Alembic environment for Studio's SQLite database.

Lives inside the package rather than beside it so the migration scripts travel
with the frozen Mac app: ``script_location`` is resolved from
``vendoo_studio.__file__``, which points into the bundle when packaged and into
the checkout otherwise.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from vendoo_studio.config import DATABASE_PATH
from vendoo_studio.database import Base, load_models

load_models()
target_metadata = Base.metadata


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or f"sqlite:///{DATABASE_PATH}"


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        # SQLite cannot ALTER much in place. Batch mode copies the table,
        # which is what lets a migration rename or drop a column at all.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
