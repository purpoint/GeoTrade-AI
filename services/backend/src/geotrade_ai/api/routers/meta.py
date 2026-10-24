from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from geotrade_ai.api.deps import DbSession
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.errors import ApiError

router = APIRouter(tags=["meta"])

DISCLAIMER = (
    "GeoTrade-AI summarises public news and automated signals. It is not investment advice and "
    "makes no buy, sell or price-target recommendations. Signals can be wrong; do your own research."
)


class Health(BaseModel):
    status: str


class Version(BaseModel):
    version: str
    llm_enabled: bool
    llm_model: str | None


class Disclaimer(BaseModel):
    text: str


@router.get("/health/live", response_model=Health)
def live() -> Health:
    return Health(status="ok")


@router.get("/health/ready", response_model=Health)
def ready(db: DbSession) -> Health:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise ApiError(503, "not_ready", "database unavailable") from exc
    return Health(status="ok")


@router.get("/meta/version", response_model=Version)
def version() -> Version:
    s = get_settings()
    model = s.llm_model if s.enable_llm else None
    return Version(version=s.app_version, llm_enabled=s.enable_llm, llm_model=model)


@router.get("/meta/disclaimer", response_model=Disclaimer)
def disclaimer() -> Disclaimer:
    return Disclaimer(text=DISCLAIMER)
