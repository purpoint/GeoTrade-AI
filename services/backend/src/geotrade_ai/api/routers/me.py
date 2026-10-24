"""Profile, preferences, password, export and delete-my-data (P2-BE-02)."""

import csv
import io
import re
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select

from geotrade_ai.api.deps import CurrentUser, DbSession
from geotrade_ai.api.routers.auth import Me, clear_session, start_session
from geotrade_ai.core import security
from geotrade_ai.core.errors import ApiError
from geotrade_ai.models import DigestDelivery, EmailPreferences, Holding, Portfolio, User, WatchlistItem
from geotrade_ai.repos import alerts as alerts_repo
from geotrade_ai.repos import users as users_repo

router = APIRouter(prefix="/me", tags=["me"])
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ATTENTION_KEYS = ("exposure", "shift", "negativity", "severity", "volume")


class QuietHours(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM.match(v):
            raise ValueError("use HH:MM (IST)")
        return v


class Preferences(BaseModel):
    attention_weights: (
        dict[Literal["exposure", "shift", "negativity", "severity", "volume"], float] | None
    ) = None
    quiet_hours: QuietHours | None = None
    alerts_enabled: bool | None = None

    @field_validator("attention_weights")
    @classmethod
    def _weights(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is not None and any(not 0 <= w <= 1 for w in v.values()):
            raise ValueError("weights must be between 0 and 1")
        return v


class MePatch(BaseModel):
    display_name: str | None = Field(None, max_length=80)
    preferences: Preferences | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=256)


class DeleteRequest(BaseModel):
    confirm: bool


@router.get("", response_model=Me)
def get_me(user: CurrentUser) -> Me:
    return Me.of(user)


@router.patch("", response_model=Me)
def patch_me(db: DbSession, user: CurrentUser, body: MePatch) -> Me:
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    if body.preferences is not None:
        user.preferences = {**user.preferences, **body.preferences.model_dump(exclude_none=True)}
    db.commit()
    return Me.of(user)


@router.post("/password", response_model=Me)
def change_password(db: DbSession, user: CurrentUser, body: PasswordChange, response: Response) -> Me:
    if user.is_demo:
        raise ApiError(403, "demo_account", "the demo account cannot change its password")
    if not security.verify_password(user.password_hash, body.current_password):
        raise ApiError(400, "invalid_password", "current password is incorrect")
    user.password_hash = security.hash_password(body.new_password)
    users_repo.revoke_all(db, user.id)  # sign out every other session
    return start_session(db, response, user)


@router.delete("", status_code=204)
def delete_me(db: DbSession, user: CurrentUser, body: DeleteRequest, response: Response) -> Response:
    if not body.confirm:
        raise ApiError(422, "confirmation_required", 'send {"confirm": true} to delete your data')
    if user.is_demo:
        raise ApiError(403, "demo_account", "the demo account cannot be deleted")
    db.execute(delete(User).where(User.id == user.id))  # every user table cascades from users
    db.commit()
    response.status_code = 204
    clear_session(response)
    return response


@router.get("/export", response_class=Response)
def export(db: DbSession, user: CurrentUser) -> Response:
    """Everything stored about the user, as CSV sections."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["section", "field", "value"])
    for field in ("email", "display_name", "role", "created_at", "disclaimer_accepted_at"):
        w.writerow(["profile", field, getattr(user, field)])
    for key, value in user.preferences.items():
        w.writerow(["preferences", key, value])
    w.writerow([])
    w.writerow(["holdings", "symbol", "ticker", "isin", "quantity", "avg_price"])
    for h in db.scalars(
        select(Holding)
        .join(Portfolio, Portfolio.id == Holding.portfolio_id)
        .where(Portfolio.user_id == user.id)
    ):
        w.writerow(["holdings", h.symbol, h.ticker or "", h.isin or "", h.quantity, h.avg_price])
    w.writerow([])
    w.writerow(["watchlist", "ticker", "added_at"])
    for item in db.scalars(select(WatchlistItem).where(WatchlistItem.user_id == user.id)):
        w.writerow(["watchlist", item.ticker, item.created_at])
    for section, rows in export_extras(db, user):
        w.writerow([])
        for row in rows:
            w.writerow([section, *row])
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="geotrade-ai-export.csv"'},
    )


def export_extras(db: DbSession, user: User) -> list[tuple[str, list[list[object]]]]:
    rules: list[list[object]] = [["kind", "enabled", "params"]]
    rules += [[r.kind, r.enabled, r.params] for r in alerts_repo.rules(db, user.id)]
    rules += [
        [f"custom: {r.source_text}", r.enabled, r.params] for r in alerts_repo.custom_rules(db, user.id)
    ]
    alerts: list[list[object]] = [["created_at", "kind", "ticker", "title", "read_at"]]
    alerts += [
        [a.created_at, a.kind, a.ticker or "", a.title, a.read_at or ""]
        for a in alerts_repo.page(db, user.id, False, 1000, None)
    ]
    email: list[list[object]] = [["daily_digest_enabled", "send_time_ist", "consented_at", "unsubscribed_at"]]
    p = db.get(EmailPreferences, user.id)
    if p is not None:
        email.append([p.daily_digest_enabled, p.send_time_ist, p.consented_at or "", p.unsubscribed_at or ""])
    digests: list[list[object]] = [["session_date", "kind", "status", "subject", "sent_at"]]
    digests += [
        [d.session_date, d.kind, d.status, d.subject or "", d.sent_at or ""]
        for d in db.scalars(select(DigestDelivery).where(DigestDelivery.user_id == user.id))
    ]
    return [("alert_rules", rules), ("alerts", alerts), ("email_preferences", email), ("digests", digests)]
