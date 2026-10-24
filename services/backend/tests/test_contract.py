"""Contract tests (P2-BE-13): generated requests against every documented operation must never
produce a server error, signed in as an operator so private and admin routes are exercised too."""

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.api.ratelimit import limiter
from geotrade_ai.core import security
from geotrade_ai.core.config import get_settings
from geotrade_ai.models import User
from geotrade_ai.repos import users as users_repo
from geotrade_ai.repos.accounts import seed_demo_accounts
from geotrade_ai.repos.reference import seed_reference


@pytest.fixture
def api_schema(session: Session, monkeypatch: pytest.MonkeyPatch) -> schemathesis.BaseSchema:
    seed_reference(session)
    session.execute(User.__table__.delete())
    session.commit()
    seed_demo_accounts(session)
    monkeypatch.setattr(get_settings(), "rate_limit_default_per_min", 100_000)
    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_min", 100_000)
    limiter.reset()
    return schemathesis.openapi.from_asgi("/api/v1/openapi.json", create_app()).exclude(path="/api/v1/stream")


@pytest.fixture
def operator_headers(session: Session) -> dict[str, str]:
    op = users_repo.ensure_operator(session, "contract-ops@example.com", "correct horse battery")
    session.commit()
    assert op is not None
    return {"Authorization": f"Bearer {security.create_access_token(op.id, 'operator')}"}


schema = schemathesis.pytest.from_fixture("api_schema")


@pytest.mark.contract
@schema.parametrize()
@settings(max_examples=8, deadline=None, suppress_health_check=list(HealthCheck))
def test_no_server_errors(case: schemathesis.Case, operator_headers: dict[str, str]) -> None:
    case.call_and_validate(headers=operator_headers, checks=[not_a_server_error])
