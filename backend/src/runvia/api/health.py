from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    status: Literal["ok"]


# Liveness must not check dependencies: a database outage would otherwise
# make Kubernetes restart healthy pods in a loop (spec §15).
@router.get("/live")
async def live() -> HealthStatus:
    return HealthStatus(status="ok")
