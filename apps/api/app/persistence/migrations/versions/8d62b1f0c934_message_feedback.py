"""Persist message-scoped user feedback."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8d62b1f0c934"
down_revision = "49545d9e93c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("feedback_json", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("messages", "feedback_json")
