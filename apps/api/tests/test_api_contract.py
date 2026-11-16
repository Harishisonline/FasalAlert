"""PRD AC 17: every operation in the OpenAPI schema answers with a documented status and, for errors, the §13
envelope; no request below produces a 500. Path parameters are filled with ids that do not exist."""
import re

import pytest

from tests.conftest import login

PUBLIC = {"/api/v1/health", "/api/v1/auth/otp/request", "/api/v1/auth/otp/verify", "/api/v1/auth/refresh", "/api/v1/auth/logout",
          "/api/v1/locations/search", "/api/v1/locations/reverse", "/api/v1/locations/districts", "/api/v1/public/risks", "/api/v1/public/districts/{district_id}"}


def _ops(client):
    spec = client.app.openapi()
    for path, item in spec["paths"].items():
        for method in item:
            yield path, method.upper()


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "999999", path)


def _assert_envelope(r):
    body = r.json()
    assert set(body) == {"error"}, body
    assert {"code", "message", "trace_id"} <= set(body["error"]), body


def test_every_protected_operation_rejects_a_missing_token_with_the_envelope(client):
    seen = 0
    for path, method in _ops(client):
        if path in PUBLIC or path.startswith("/api/v1/locations/") or not path.startswith("/api/v1/"):   # onboarding is pre-sign-in
            continue
        r = client.request(method, _url(path), json={} if method in ("POST", "PATCH", "PUT") else None)
        assert r.status_code == 401, (method, path, r.status_code, r.text[:200])
        _assert_envelope(r)
        seen += 1
    assert seen >= 25


@pytest.mark.parametrize("bad_token", ["Bearer not-a-jwt", "Basic abc"])
def test_a_bad_token_is_401_with_the_envelope(client, bad_token):
    r = client.get("/api/v1/users/me", headers={"Authorization": bad_token})
    assert r.status_code == 401
    _assert_envelope(r)


def test_every_operation_with_a_valid_token_never_500s(client, monkeypatch):
    from app.services.decision import engine

    # no network in the default suite: decisions that need a forecast degrade to their documented errors
    monkeypatch.setattr(engine, "get_forecast", lambda *a, **k: (_ for _ in ()).throw(engine.UpstreamError("offline test")))
    h = login(client)["headers"]
    for path, method in _ops(client):
        if not path.startswith("/api/v1/") or path in ("/api/v1/auth/logout",):
            continue
        r = client.request(method, _url(path), headers=h, json={} if method in ("POST", "PATCH", "PUT") else None)
        assert r.status_code < 500 or r.status_code == 503, (method, path, r.status_code, r.text[:300])
        if r.status_code >= 400:
            _assert_envelope(r)
