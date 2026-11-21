from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.infrastructure import InfrastructureQueries
from app.services.twin_store import LoadedTwin, TwinStore


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_twin_store(request: Request) -> TwinStore:
    store: TwinStore = request.app.state.twin_store
    return store


async def get_twin(
    session: SessionDep, store: Annotated[TwinStore, Depends(get_twin_store)]
) -> LoadedTwin:
    return await store.current(session)


TwinDep = Annotated[LoadedTwin, Depends(get_twin)]


async def get_queries(twin: Annotated[LoadedTwin, Depends(get_twin)]) -> InfrastructureQueries:
    return InfrastructureQueries(twin)


QueriesDep = Annotated[InfrastructureQueries, Depends(get_queries)]
