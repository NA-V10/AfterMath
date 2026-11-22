from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import SessionDep
from app.services.reports import IncidentReport, build_report, render_markdown

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentReport,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def incident_report(
    incident_id: uuid.UUID,
    session: SessionDep,
    format_: Annotated[Literal["json", "markdown"], Query(alias="format")] = "json",
) -> IncidentReport | PlainTextResponse:
    """The full recovery report for an incident, built only from stored records."""
    report = await build_report(session, incident_id)
    if format_ == "markdown":
        return PlainTextResponse(
            render_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{report.incident["reference"]}-report.md"'
                )
            },
        )
    return report
