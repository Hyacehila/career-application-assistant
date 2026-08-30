"""Reset endpoint available only in isolated Demo mode."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..demo import reset_demo_data

router = APIRouter(prefix="/api/demo", tags=["demo"])


class DemoResetRequest(BaseModel):
    model_config = {"extra": "forbid"}


@router.post("/reset")
def reset_demo(request: Request, _: DemoResetRequest) -> dict[str, int | bool]:
    records_seeded = reset_demo_data(request.app.state.paths)
    return {"ok": True, "records_seeded": records_seeded}
