from fastapi.testclient import TestClient

from geotrade_ai.api.app import create_app
from geotrade_ai.core.ids import uuid7


def test_uuid7_version_and_order() -> None:
    ids = [uuid7() for _ in range(50)]
    assert all(u.version == 7 for u in ids)
    # same-millisecond ids may tie on the timestamp, so compare the 48-bit prefix only
    stamps = [u.int >> 80 for u in ids]
    assert stamps == sorted(stamps)


def test_meta_endpoints_and_request_id() -> None:
    client = TestClient(create_app())
    r = client.get("/api/v1/health/live", headers={"X-Request-ID": "abc"})
    assert r.json() == {"status": "ok"}
    assert r.headers["X-Request-ID"] == "abc"
    assert "not investment advice" in client.get("/api/v1/meta/disclaimer").json()["text"]


def test_unified_error_format() -> None:
    r = TestClient(create_app()).get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert r.json()["error"]["request_id"]
