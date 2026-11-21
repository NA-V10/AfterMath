"""Who is acting. Until authentication lands (Phase 5) a fixed local identity is used, and only
outside production (docs/SECURITY.md §3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException

from app.core.config import get_settings

LOCAL_DEV_ACTOR = "local:operator"


def current_actor() -> str:
    if get_settings().aftermath_env == "production":
        raise HTTPException(status_code=401, detail="Authentication is required.")
    return LOCAL_DEV_ACTOR


ActorDep = Annotated[str, Depends(current_actor)]
