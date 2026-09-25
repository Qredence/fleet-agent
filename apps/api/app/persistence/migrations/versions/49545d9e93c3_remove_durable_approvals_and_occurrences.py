"""drop approval checkpoints and source occurrences

Revision ID: 49545d9e93c3
Revises: 7c3d9f1a2b8e
Create Date: 2026-09-17 08:04:56.787075

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "49545d9e93c3"
down_revision: str | Sequence[str] | None = "7c3d9f1a2b8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("runs", "reserved_at", server_default=sa.text("now()"))

    op.drop_index(
        "ix_approval_checkpoints_run_status", table_name="approval_checkpoints"
    )
    op.drop_index(
        op.f("ix_approval_checkpoints_run_id"), table_name="approval_checkpoints"
    )
    op.drop_index(
        op.f("ix_approval_checkpoints_thread_id"), table_name="approval_checkpoints"
    )
    op.drop_table("approval_checkpoints")

    op.drop_index("ix_source_occurrences_source", table_name="source_occurrences")
    op.drop_table("source_occurrences")


def downgrade() -> None:
    op.create_table(
        "source_occurrences",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_row_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("tool_call_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("uri", sa.String(), nullable=True),
        sa.Column("excerpt", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_row_id"], ["sources.row_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_occurrences_source", "source_occurrences", ["source_row_id"]
    )

    op.create_table(
        "approval_checkpoints",
        sa.Column("interrupt_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("provider_binding", sa.String(), nullable=False),
        sa.Column("profile_name", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_call_id", sa.String(), nullable=False),
        sa.Column("assistant_message_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "checkpoint_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("dspy_version", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("interrupt_id"),
    )
    op.create_index(
        "ix_approval_checkpoints_run_status",
        "approval_checkpoints",
        ["run_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_checkpoints_run_id"),
        "approval_checkpoints",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_checkpoints_thread_id"),
        "approval_checkpoints",
        ["thread_id"],
        unique=False,
    )
    op.alter_column("runs", "reserved_at", server_default=None)
