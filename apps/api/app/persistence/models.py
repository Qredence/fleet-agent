"""SQLAlchemy models per plan.md Phase 9.

* `messages.message_json` holds the AG-UI wire message — restored as-is.
* `run_states.state_json` is an AgentWorkspaceState snapshot per run/head.
* `dspy_histories.history_json` is the serialized dspy.History per branch head
  — server-side ONLY (contains raw next_thought), versioned with DSPy.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String, default="local", server_default="local"
    )
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, default="active", server_default="active"
    )
    last_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_head_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String)
    message_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    format: Mapped[str] = mapped_column(
        String, default="ag-ui/v1", server_default="ag-ui/v1"
    )
    message_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    run_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "thread_id", "message_id", name="uq_messages_thread_message_id"
        ),
        Index("ix_messages_thread_parent", "thread_id", "parent_message_id"),
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    termination_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    input_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    continuation_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    output_message_id: Mapped[str | None] = mapped_column(String, nullable=True)


class RunState(Base):
    """Branch-aware AgentWorkspaceState snapshot (panel restoration)."""

    __tablename__ = "run_states"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    head_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "head_message_id",
            name="uq_run_states_thread_head_message",
        ),
    )


class DspyHistory(Base):
    """Server-side continuation history per branch head — never client-facing."""

    __tablename__ = "dspy_histories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    head_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    schema_version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    dspy_version: Mapped[str] = mapped_column(String)
    history_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "head_message_id",
            name="uq_dspy_histories_thread_head_message",
        ),
    )


class Source(Base):
    __tablename__ = "sources"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(String)
    identity_key: Mapped[str] = mapped_column(String, nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    uri: Mapped[str | None] = mapped_column(String, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "thread_id", "identity_key", name="uq_sources_thread_identity"
        ),
        Index("ix_sources_thread_public_id", "thread_id", "id"),
    )


class SourceOccurrence(Base):
    """Every discovery of a canonical source, including repeated runs."""

    __tablename__ = "source_occurrences"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_row_id: Mapped[str] = mapped_column(
        ForeignKey("sources.row_id", ondelete="CASCADE")
    )
    run_id: Mapped[str] = mapped_column(String)
    tool_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    uri: Mapped[str | None] = mapped_column(String, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_source_occurrences_source", "source_row_id"),)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String, unique=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String, default="generating", server_default="generating"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
