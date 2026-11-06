"""Add saved tabular import profiles.

Revision ID: 0002_import_profiles
Revises: 0001_initial
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_import_profiles"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "import_profiles" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("import_profiles")}
        if "campus_rules" not in columns:
            op.add_column(
                "import_profiles",
                sa.Column(
                    "campus_rules",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                ),
            )
        return
    op.create_table(
        "import_profiles",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column("course_column", sa.String(length=80), nullable=False),
        sa.Column("time_column", sa.String(length=80), nullable=False),
        sa.Column("location_column", sa.String(length=80), nullable=False),
        sa.Column("teacher_column", sa.String(length=80), nullable=False),
        sa.Column("multi_separator", sa.String(length=10), nullable=False),
        sa.Column("odd_marker", sa.String(length=10), nullable=False),
        sa.Column("even_marker", sa.String(length=10), nullable=False),
        sa.Column(
            "time_regex",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "campus_rules",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "import_profiles" in inspector.get_table_names():
        op.drop_table("import_profiles")
