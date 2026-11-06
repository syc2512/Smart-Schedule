"""Add optional custom time regex to import profiles.

Revision ID: 0003_import_profile_time_regex
Revises: 0002_import_profiles
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_import_profile_time_regex"
down_revision = "0002_import_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("import_profiles")}
    if "time_regex" not in columns:
        op.add_column(
            "import_profiles",
            sa.Column(
                "time_regex",
                sa.String(length=500),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("import_profiles")}
    if "time_regex" in columns:
        op.drop_column("import_profiles", "time_regex")
