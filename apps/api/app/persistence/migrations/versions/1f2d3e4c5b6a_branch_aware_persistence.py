"""Add branch-aware message and run persistence.

The previous revisions stored one linear message/history/state row per thread.
This migration keeps those rows and adds the identities required to represent
assistant-ui branches without exposing DSPy internals to the client.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1f2d3e4c5b6a"
down_revision: str | Sequence[str] | None = "6aa77657c517"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "threads", sa.Column("active_head_message_id", sa.String(), nullable=True)
    )

    op.add_column("messages", sa.Column("message_id", sa.String(), nullable=True))
    op.add_column(
        "messages", sa.Column("parent_message_id", sa.String(), nullable=True)
    )
    op.add_column(
        "messages",
        sa.Column("format", sa.String(), server_default="ag-ui/v1", nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column(
            "run_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
    )
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                item RECORD;
                base_id TEXT;
                candidate_id TEXT;
                suffix INTEGER;
            BEGIN
                FOR item IN
                    SELECT id, thread_id, message_json
                    FROM messages
                    ORDER BY thread_id, created_at, id
                LOOP
                    base_id := NULLIF(item.message_json ->> 'id', '');
                    IF base_id IS NULL THEN
                        base_id := 'legacy-' || item.id;
                    END IF;
                    candidate_id := base_id;
                    suffix := 0;
                    WHILE EXISTS (
                        SELECT 1
                        FROM messages
                        WHERE thread_id = item.thread_id
                          AND message_id = candidate_id
                          AND id <> item.id
                    ) LOOP
                        suffix := suffix + 1;
                        candidate_id := base_id || '--' || suffix;
                    END LOOP;
                    UPDATE messages
                    SET message_id = candidate_id,
                        format = 'ag-ui/v1',
                        updated_at = COALESCE(updated_at, now()),
                        message_json = jsonb_set(
                            COALESCE(message_json, '{}'::jsonb),
                            '{id}',
                            to_jsonb(candidate_id),
                            true
                        )
                    WHERE id = item.id;
                END LOOP;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ordered AS (
                SELECT id,
                       LAG(message_id) OVER (
                           PARTITION BY thread_id ORDER BY created_at, id
                       ) AS parent_id
                FROM messages
            )
            UPDATE messages AS message
            SET parent_message_id = ordered.parent_id
            FROM ordered
            WHERE message.id = ordered.id
            """
        )
    )
    op.alter_column("messages", "message_id", nullable=False)
    op.alter_column("messages", "format", nullable=False)
    op.alter_column("messages", "updated_at", nullable=False)
    op.create_unique_constraint(
        "uq_messages_thread_message_id", "messages", ["thread_id", "message_id"]
    )
    op.create_index(
        "ix_messages_thread_parent", "messages", ["thread_id", "parent_message_id"]
    )

    op.execute(
        sa.text(
            """
            UPDATE threads AS thread
            SET active_head_message_id = latest.message_id
            FROM (
                SELECT DISTINCT ON (thread_id) thread_id, message_id
                FROM messages
                ORDER BY thread_id, created_at DESC, id DESC
            ) AS latest
            WHERE thread.id = latest.thread_id
            """
        )
    )

    op.add_column(
        "runs",
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("runs", sa.Column("input_message_id", sa.String(), nullable=True))
    op.add_column(
        "runs", sa.Column("continuation_message_id", sa.String(), nullable=True)
    )
    op.add_column("runs", sa.Column("output_message_id", sa.String(), nullable=True))
    op.execute(sa.text("UPDATE runs SET reserved_at = COALESCE(started_at, now())"))
    op.alter_column("runs", "reserved_at", nullable=False)
    op.alter_column("runs", "started_at", nullable=True)

    op.add_column("run_states", sa.Column("id", sa.String(), nullable=True))
    op.add_column("run_states", sa.Column("run_id", sa.String(), nullable=True))
    op.add_column(
        "run_states", sa.Column("head_message_id", sa.String(), nullable=True)
    )
    op.execute(
        sa.text(
            """
            UPDATE run_states AS state
            SET id = 'state-legacy-' || state.thread_id,
                run_id = thread.last_run_id,
                head_message_id = thread.active_head_message_id
            FROM threads AS thread
            WHERE thread.id = state.thread_id
            """
        )
    )
    op.alter_column("run_states", "id", nullable=False)
    op.drop_constraint("run_states_pkey", "run_states", type_="primary")
    op.create_primary_key("run_states_pkey", "run_states", ["id"])
    op.create_index("ix_run_states_run_id", "run_states", ["run_id"])
    op.create_unique_constraint(
        "uq_run_states_thread_head_message",
        "run_states",
        ["thread_id", "head_message_id"],
    )
    op.create_index("ix_run_states_thread_id", "run_states", ["thread_id"])

    op.add_column("dspy_histories", sa.Column("id", sa.String(), nullable=True))
    op.add_column(
        "dspy_histories", sa.Column("head_message_id", sa.String(), nullable=True)
    )
    op.execute(
        sa.text(
            """
            UPDATE dspy_histories AS history
            SET id = 'history-legacy-' || history.thread_id,
                head_message_id = thread.active_head_message_id
            FROM threads AS thread
            WHERE thread.id = history.thread_id
            """
        )
    )
    op.alter_column("dspy_histories", "id", nullable=False)
    op.drop_constraint("dspy_histories_pkey", "dspy_histories", type_="primary")
    op.create_primary_key("dspy_histories_pkey", "dspy_histories", ["id"])
    op.create_index("ix_dspy_histories_thread_id", "dspy_histories", ["thread_id"])
    op.create_unique_constraint(
        "uq_dspy_histories_thread_head_message",
        "dspy_histories",
        ["thread_id", "head_message_id"],
    )

    op.add_column("sources", sa.Column("row_id", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("identity_key", sa.String(), nullable=True))
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                item RECORD;
                clean_uri TEXT;
                scheme TEXT;
                authority TEXT;
                suffix TEXT;
                path_part TEXT;
                query_part TEXT;
                canonical TEXT;
            BEGIN
                FOR item IN SELECT row_id, id, uri FROM sources LOOP
                    IF item.uri IS NULL OR btrim(item.uri) = '' THEN
                        canonical := 'id:' || item.id;
                    ELSE
                        clean_uri := regexp_replace(btrim(item.uri), '#.*$', '');
                        IF clean_uri ~ '^[A-Za-z][A-Za-z0-9+.-]*://'
                        THEN
                            scheme := lower(
                                substring(
                                    clean_uri
                                    FROM '^([A-Za-z][A-Za-z0-9+.-]*):'
                                )
                            );
                            authority := lower(
                                substring(
                                    clean_uri
                                    FROM '^[A-Za-z][A-Za-z0-9+.-]*://([^/?#]*)'
                                )
                            );
                            suffix := coalesce(
                                substring(
                                    clean_uri
                                    FROM '^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]*(.*)$'
                                ),
                                ''
                            );
                            path_part := split_part(suffix, '?', 1);
                            path_part := regexp_replace(path_part, '/+$', '');
                            query_part := CASE
                                WHEN position('?' IN suffix) > 0
                                THEN substring(suffix FROM position('?' IN suffix) + 1)
                                ELSE ''
                            END;
                            canonical := scheme || '://' || authority || path_part;
                            IF query_part <> '' THEN
                                canonical := canonical || '?' || query_part;
                            END IF;
                        ELSE
                            -- Match urlsplit/urlunsplit for legacy values
                            -- without an authority component.
                            scheme := substring(
                                clean_uri FROM '^([A-Za-z][A-Za-z0-9+.-]*):'
                            );
                            IF scheme IS NOT NULL THEN
                                scheme := lower(scheme) || ':';
                                suffix := substring(
                                    clean_uri FROM '^[A-Za-z][A-Za-z0-9+.-]*:(.*)$'
                                );
                            ELSE
                                scheme := 'https:';
                                suffix := clean_uri;
                            END IF;
                            path_part := split_part(suffix, '?', 1);
                            path_part := regexp_replace(path_part, '/+$', '');
                            query_part := CASE
                                WHEN position('?' IN suffix) > 0
                                THEN substring(suffix FROM position('?' IN suffix) + 1)
                                ELSE ''
                            END;
                            canonical := CASE
                                WHEN path_part LIKE '/%'
                                THEN concat(scheme, '//', path_part)
                                ELSE scheme || path_part
                            END;
                            IF query_part <> '' THEN
                                canonical := canonical || '?' || query_part;
                            END IF;
                        END IF;
                    END IF;
                    UPDATE sources
                    SET row_id = 'source-row-' || item.id,
                        identity_key = canonical
                    WHERE id = item.id;
                END LOOP;
            END $$;
            """
        )
    )
    op.alter_column("sources", "row_id", nullable=False)
    op.alter_column("sources", "identity_key", nullable=False)
    op.drop_constraint("sources_pkey", "sources", type_="primary")
    op.create_primary_key("sources_pkey", "sources", ["row_id"])
    op.create_index("ix_sources_thread_public_id", "sources", ["thread_id", "id"])

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
        sa.Index("ix_source_occurrences_source", "source_row_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO source_occurrences
                (
                    id, source_row_id, run_id, tool_call_id,
                    title, source_type, uri, excerpt
                )
            SELECT 'occurrence-legacy-' || row_id,
                   row_id, run_id, tool_call_id, title, source_type, uri, excerpt
            FROM sources
            """
        )
    )

    # Existing databases are normally duplicate-free. If a legacy database
    # contains two source rows for one canonical URI, keep the rows intact and
    # suffix only the older identity key so no user data is deleted; new writes
    # use the unsuffixed canonical key and deduplicate going forward.
    op.execute(
        sa.text(
            """
            WITH duplicates AS (
                SELECT row_id,
                       identity_key,
                       ROW_NUMBER() OVER (
                           PARTITION BY thread_id, identity_key
                           ORDER BY created_at, row_id
                       ) AS duplicate_number
                FROM sources
            )
            UPDATE sources AS source
            SET identity_key = duplicates.identity_key || ':legacy:' || source.row_id
            FROM duplicates
            WHERE source.row_id = duplicates.row_id
              AND duplicates.duplicate_number > 1
            """
        )
    )
    op.create_unique_constraint(
        "uq_sources_thread_identity", "sources", ["thread_id", "identity_key"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    branch_count = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM messages WHERE format <> 'ag-ui/v1'
            UNION ALL
            SELECT count(*)
            FROM (
                SELECT thread_id, parent_message_id
                FROM messages
                GROUP BY thread_id, parent_message_id
                HAVING count(*) > 1
            ) AS branched_parents
            UNION ALL
            SELECT count(*)
            FROM run_states
            GROUP BY thread_id
            HAVING count(*) > 1
            UNION ALL
            SELECT count(*)
            FROM dspy_histories
            GROUP BY thread_id
            HAVING count(*) > 1
            UNION ALL
            SELECT count(*)
            FROM sources
            GROUP BY id
            HAVING count(*) > 1
            """
        )
    ).all()
    if any(int(row[0]) for row in branch_count):
        raise RuntimeError(
            "Cannot downgrade branch-aware persistence while branch/message "
            "data exists."
        )

    # The previous schema requires every run to have started_at.  Queued runs
    # introduced by this revision may legitimately still be NULL, so do not
    # let the final ALTER fail with an opaque driver error after destructive
    # downgrade steps have already run.
    null_started = int(
        bind.execute(
            sa.text("SELECT count(*) FROM runs WHERE started_at IS NULL")
        ).scalar_one()
    )
    if null_started:
        raise RuntimeError(
            "Cannot downgrade branch-aware persistence while runs have NULL "
            "started_at; settle or remove those runs first."
        )

    op.drop_constraint("uq_sources_thread_identity", "sources", type_="unique")
    op.drop_table("source_occurrences")
    op.drop_index("ix_sources_thread_public_id", table_name="sources")
    op.drop_constraint("sources_pkey", "sources", type_="primary")
    op.create_primary_key("sources_pkey", "sources", ["id"])
    op.drop_column("sources", "identity_key")
    op.drop_column("sources", "row_id")

    op.drop_constraint(
        "uq_dspy_histories_thread_head_message", "dspy_histories", type_="unique"
    )
    op.drop_index("ix_dspy_histories_thread_id", table_name="dspy_histories")
    op.drop_constraint("dspy_histories_pkey", "dspy_histories", type_="primary")
    op.create_primary_key("dspy_histories_pkey", "dspy_histories", ["thread_id"])
    op.drop_column("dspy_histories", "head_message_id")
    op.drop_column("dspy_histories", "id")

    op.drop_constraint(
        "uq_run_states_thread_head_message", "run_states", type_="unique"
    )
    op.drop_index("ix_run_states_thread_id", table_name="run_states")
    op.drop_index("ix_run_states_run_id", table_name="run_states")
    op.drop_constraint("run_states_pkey", "run_states", type_="primary")
    op.create_primary_key("run_states_pkey", "run_states", ["thread_id"])
    op.drop_column("run_states", "head_message_id")
    op.drop_column("run_states", "run_id")
    op.drop_column("run_states", "id")

    op.drop_column("runs", "output_message_id")
    op.drop_column("runs", "continuation_message_id")
    op.drop_column("runs", "input_message_id")
    op.drop_column("runs", "reserved_at")
    op.alter_column("runs", "started_at", nullable=False)

    op.drop_index("ix_messages_thread_parent", table_name="messages")
    op.drop_constraint("uq_messages_thread_message_id", "messages", type_="unique")
    op.drop_column("messages", "updated_at")
    op.drop_column("messages", "run_config_json")
    op.drop_column("messages", "format")
    op.drop_column("messages", "parent_message_id")
    op.drop_column("messages", "message_id")
    op.drop_column("threads", "active_head_message_id")
