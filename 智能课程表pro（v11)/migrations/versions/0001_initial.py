"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-05
"""

from __future__ import annotations

from alembic import op

from server.app import models  # noqa: F401
from server.app.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create_all is safe here because this is the baseline for both new and
    # pre-Alembic databases. Existing tables are left untouched.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
