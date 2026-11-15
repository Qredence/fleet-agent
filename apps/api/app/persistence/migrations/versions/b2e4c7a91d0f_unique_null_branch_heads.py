"""Enforce unique root/null branch heads on run_states and dspy_histories."""

import sqlalchemy as sa
from alembic import op

revision = "b2e4c7a91d0f"
down_revision = "8d62b1f0c934"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM run_states
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY thread_id ORDER BY updated_at DESC, id DESC
                ) AS rn
                FROM run_states
                WHERE head_message_id IS NULL
            ) ranked
            WHERE rn > 1
        )
        """
    )
    op.execute(
        """
        DELETE FROM dspy_histories
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY thread_id ORDER BY updated_at DESC, id DESC
                ) AS rn
                FROM dspy_histories
                WHERE head_message_id IS NULL
            ) ranked
            WHERE rn > 1
        )
        """
    )
    op.create_index(
        "uq_run_states_thread_null_head",
        "run_states",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text("head_message_id IS NULL"),
    )
    op.create_index(
        "uq_dspy_histories_thread_null_head",
        "dspy_histories",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text("head_message_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_dspy_histories_thread_null_head", table_name="dspy_histories")
    op.drop_index("uq_run_states_thread_null_head", table_name="run_states")
