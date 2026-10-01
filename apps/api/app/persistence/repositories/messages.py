"""Message branch-node queries."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.kernel.history_safety import sanitize_message_content
from app.persistence.models import Message
from app.persistence.repositories.helpers import new_id


class MessagesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(
        self,
        *,
        thread_id: str,
        role: str,
        message_json: dict[str, Any],
        message_id: str | None = None,
        parent_message_id: str | None = None,
        format: str = "ag-ui/v1",
        run_config_json: dict[str, Any] | None = None,
    ) -> Message:
        async with self._sessions() as session:
            row = await self.upsert_in_session(
                session,
                thread_id=thread_id,
                role=role,
                message_json=message_json,
                message_id=message_id,
                parent_message_id=parent_message_id,
                format=format,
                run_config_json=run_config_json,
            )
            await session.commit()
            return row

    @staticmethod
    async def upsert_in_session(
        session: AsyncSession,
        *,
        thread_id: str,
        role: str,
        message_json: dict[str, Any],
        message_id: str | None = None,
        parent_message_id: str | None = None,
        format: str = "ag-ui/v1",
        run_config_json: dict[str, Any] | None = None,
    ) -> Message:
        resolved_id = message_id or str(message_json.get("id") or new_id("message"))
        if parent_message_id == resolved_id:
            raise ValueError("A message cannot parent itself.")
        result = await session.execute(
            select(Message)
            .where(
                Message.thread_id == thread_id,
                Message.message_id == resolved_id,
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = Message(
                id=new_id("message_row"),
                thread_id=thread_id,
                message_id=resolved_id,
                parent_message_id=parent_message_id,
                role=role,
                format=format,
                message_json=message_json,
                run_config_json=run_config_json,
            )
            session.add(row)
            await session.flush()
            return row

        if row.role != role:
            raise ValueError("Message role does not match the existing branch node.")
        if row.parent_message_id not in (None, parent_message_id):
            raise ValueError("Message parent does not match the existing branch node.")
        # A server fallback must never overwrite an exact assistant-ui row.
        if row.format != "aui/v0" or format == "aui/v0":
            row.format = format
            row.message_json = message_json
            if run_config_json is not None or format != "aui/v0":
                row.run_config_json = run_config_json
        if row.parent_message_id is None:
            row.parent_message_id = parent_message_id
        row.updated_at = datetime.now(UTC)
        await session.flush()
        return row

    @staticmethod
    def storage_dict(row: Message) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": row.message_id,
            "parentId": row.parent_message_id,
            "format": row.format,
            "content": sanitize_message_content(row.message_json),
        }
        if row.run_config_json is not None:
            item["runConfig"] = sanitize_message_content(row.run_config_json)
        return item

    async def list_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Message.message_json)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
            return list(rows.scalars())
