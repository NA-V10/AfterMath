"""Process-wide cache of the current twin (snapshot + graph), keyed by the release hash."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger
from app.database import repositories as repo
from app.graph.model import TwinSnapshot
from app.graph.twin_graph import TwinGraph

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadedTwin:
    snapshot: TwinSnapshot
    graph: TwinGraph
    ids: dict[str, uuid.UUID]
    basemap: dict[str, Any]
    release_hash: str


class TwinStore:
    def __init__(self) -> None:
        self._cached: LoadedTwin | None = None
        self._lock = asyncio.Lock()

    async def current(self, session: AsyncSession) -> LoadedTwin:
        release = await repo.current_release(session)
        if release is None:
            raise ServiceUnavailableError(
                "No dataset is loaded. Run `uv run python -m app.cli seed` in backend/."
            )
        cached = self._cached
        if cached is not None and cached.release_hash == release.content_hash:
            return cached
        async with self._lock:
            if self._cached is not None and self._cached.release_hash == release.content_hash:
                return self._cached
            snapshot, ids = await repo.load_snapshot(session, release)
            if snapshot.content_hash != release.content_hash:
                # Rows were modified outside the seeding process: refuse to serve them.
                log.error(
                    "twin_integrity_failure",
                    expected=release.content_hash,
                    actual=snapshot.content_hash,
                )
                raise ServiceUnavailableError(
                    "Twin integrity check failed: stored assets do not match the seeded "
                    "dataset release. Re-seed the dataset."
                )
            loaded = LoadedTwin(
                snapshot, TwinGraph(snapshot), ids, release.basemap, release.content_hash
            )
            self._cached = loaded
            log.info("twin_loaded", version=snapshot.dataset_version, assets=len(snapshot.assets))
            return loaded
