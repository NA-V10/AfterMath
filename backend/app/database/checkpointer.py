"""LangGraph checkpoint saver on PostgreSQL via SQLAlchemy/asyncpg.

The official `langgraph-checkpoint-postgres` requires psycopg 3, whose bundled libpq is blocked by
Windows Application Control on the development host (docs/ENVIRONMENT.md). This saver follows the
storage design of LangGraph's `InMemorySaver` (checkpoints, per-channel versioned blobs, pending
writes) and is exercised by tests against a real database. Async-only: the sync API is unused.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    writes_sort_key,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


class AsyncpgCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__()
        self.engine = engine

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _cfg(thread_id: str, ns: str, checkpoint_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def _load_blobs(
        self, conn: AsyncConnection, thread_id: str, ns: str, versions: ChannelVersions
    ) -> dict[str, Any]:
        if not versions:
            return {}
        rows = await conn.execute(
            text(
                "SELECT channel, version, type, blob FROM lg_checkpoint_blob "
                "WHERE thread_id = :t AND checkpoint_ns = :ns AND channel = ANY(:channels)"
            ),
            {"t": thread_id, "ns": ns, "channels": list(versions)},
        )
        values: dict[str, Any] = {}
        for channel, version, type_, blob in rows.all():
            if str(versions.get(channel)) == version and type_ != "empty":
                values[channel] = self.serde.loads_typed((type_, bytes(blob)))
        return values

    async def _writes(
        self, conn: AsyncConnection, thread_id: str, ns: str, checkpoint_id: str
    ) -> list[tuple[str, str, Any]]:
        rows = (
            await conn.execute(
                text(
                    "SELECT task_id, idx, channel, type, blob, task_path FROM lg_checkpoint_write "
                    "WHERE thread_id = :t AND checkpoint_ns = :ns AND checkpoint_id = :c"
                ),
                {"t": thread_id, "ns": ns, "c": checkpoint_id},
            )
        ).all()
        ordered = sorted(rows, key=lambda r: writes_sort_key(r.task_path, r.task_id, r.idx))
        return [
            (r.task_id, r.channel, self.serde.loads_typed((r.type, bytes(r.blob)))) for r in ordered
        ]

    async def _tuple(self, conn: AsyncConnection, row: Any) -> CheckpointTuple:
        checkpoint: Checkpoint = self.serde.loads_typed((row.type, bytes(row.checkpoint)))
        return CheckpointTuple(
            config=self._cfg(row.thread_id, row.checkpoint_ns, row.checkpoint_id),
            checkpoint={
                **checkpoint,
                "channel_values": await self._load_blobs(
                    conn, row.thread_id, row.checkpoint_ns, checkpoint["channel_versions"]
                ),
            },
            metadata=self.serde.loads_typed((row.metadata_type, bytes(row.metadata))),
            parent_config=(
                self._cfg(row.thread_id, row.checkpoint_ns, row.parent_checkpoint_id)
                if row.parent_checkpoint_id
                else None
            ),
            pending_writes=await self._writes(
                conn, row.thread_id, row.checkpoint_ns, row.checkpoint_id
            ),
        )

    # ------------------------------------------------------------------ async API
    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        sql = (
            "SELECT * FROM lg_checkpoint WHERE thread_id = :t AND checkpoint_ns = :ns "
            + ("AND checkpoint_id = :c " if checkpoint_id else "")
            + "ORDER BY checkpoint_id DESC LIMIT 1"
        )
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(text(sql), {"t": thread_id, "ns": ns, "c": checkpoint_id})
            ).first()
            return await self._tuple(conn, row) if row else None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        clauses, params = [], {}
        if config:
            clauses.append("thread_id = :t")
            params["t"] = config["configurable"]["thread_id"]
            if (ns := config["configurable"].get("checkpoint_ns")) is not None:
                clauses.append("checkpoint_ns = :ns")
                params["ns"] = ns
        if before and (before_id := get_checkpoint_id(before)):
            clauses.append("checkpoint_id < :before")
            params["before"] = before_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(f"SELECT * FROM lg_checkpoint {where} ORDER BY checkpoint_id DESC"),
                    params,
                )
            ).all()
            yielded = 0
            for row in rows:
                tup = await self._tuple(conn, row)
                if filter and any(tup.metadata.get(k) != v for k, v in filter.items()):
                    continue
                yield tup
                yielded += 1
                if limit is not None and yielded >= limit:
                    return

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        c = checkpoint.copy()
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        values: dict[str, Any] = c.pop("channel_values")  # type: ignore[misc]
        cp_type, cp_blob = self.serde.dumps_typed(c)
        md_type, md_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        async with self.engine.begin() as conn:
            for channel, version in new_versions.items():
                type_, blob = (
                    self.serde.dumps_typed(values[channel]) if channel in values else ("empty", b"")
                )
                await conn.execute(
                    text(
                        "INSERT INTO lg_checkpoint_blob "
                        "(thread_id, checkpoint_ns, channel, version, type, blob) "
                        "VALUES (:t, :ns, :ch, :v, :type, :blob) "
                        "ON CONFLICT (thread_id, checkpoint_ns, channel, version) DO NOTHING"
                    ),
                    {
                        "t": thread_id,
                        "ns": ns,
                        "ch": channel,
                        "v": str(version),
                        "type": type_,
                        "blob": blob,
                    },
                )
            await conn.execute(
                text(
                    "INSERT INTO lg_checkpoint (thread_id, checkpoint_ns, checkpoint_id, "
                    "parent_checkpoint_id, type, checkpoint, metadata_type, metadata) "
                    "VALUES (:t, :ns, :c, :p, :type, :cp, :mt, :md) "
                    "ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET "
                    "type = EXCLUDED.type, checkpoint = EXCLUDED.checkpoint, "
                    "metadata_type = EXCLUDED.metadata_type, metadata = EXCLUDED.metadata"
                ),
                {
                    "t": thread_id,
                    "ns": ns,
                    "c": checkpoint["id"],
                    "p": config["configurable"].get("checkpoint_id"),
                    "type": cp_type,
                    "cp": cp_blob,
                    "mt": md_type,
                    "md": md_blob,
                },
            )
        return self._cfg(thread_id, ns, checkpoint["id"])

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        async with self.engine.begin() as conn:
            for idx, (channel, value) in enumerate(writes):
                write_idx = WRITES_IDX_MAP.get(channel, idx)
                type_, blob = self.serde.dumps_typed(value)
                # Regular writes are idempotent (first wins); special channels overwrite.
                conflict = (
                    "DO NOTHING"
                    if write_idx >= 0
                    else "DO UPDATE SET channel = EXCLUDED.channel, type = EXCLUDED.type, "
                    "blob = EXCLUDED.blob, task_path = EXCLUDED.task_path"
                )
                await conn.execute(
                    text(
                        "INSERT INTO lg_checkpoint_write (thread_id, checkpoint_ns, checkpoint_id, "
                        "task_id, idx, channel, type, blob, task_path) "
                        "VALUES (:t, :ns, :c, :task, :idx, :ch, :type, :blob, :path) "
                        "ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) "
                        + conflict
                    ),
                    {
                        "t": thread_id,
                        "ns": ns,
                        "c": checkpoint_id,
                        "task": task_id,
                        "idx": write_idx,
                        "ch": channel,
                        "type": type_,
                        "blob": blob,
                        "path": task_path,
                    },
                )

    async def adelete_thread(self, thread_id: str) -> None:
        async with self.engine.begin() as conn:
            for table in ("lg_checkpoint_write", "lg_checkpoint_blob", "lg_checkpoint"):
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE thread_id = :t"), {"t": thread_id}
                )

    def get_next_version(self, current: str | None, channel: None) -> str:
        """Monotonic string versions (same scheme as LangGraph's InMemorySaver)."""
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(str(current).split(".")[0])
        return f"{current_v + 1:032}.{random.random():016}"  # noqa: S311
