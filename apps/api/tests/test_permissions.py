"""Farmer data isolation: another user's field is a 404, never a 403 (PRD §7.4)."""
from app.models.tables import Field, Fpo, FpoMember
from tests.conftest import login

A, B = "+919876543210", "+919812345678"


def _field(db, user_id):
    f = Field(user_id=user_id, name="Mango field 1", crop="mango", lat=18.15, lon=74.58)
    db.add(f)
    db.commit()
    return f.id


def test_other_users_field_is_not_found(client, db):
    a, b = login(client, A), login(client, B)
    fid = _field(db, a["user"]["id"])
    for path in (f"/api/v1/fields/{fid}", f"/api/v1/fields/{fid}/decisions", f"/api/v1/fields/{fid}/calibration",
                 f"/api/v1/risks/active?field_id={fid}", f"/api/v1/transport/risk?field_id={fid}",
                 f"/api/v1/weather/forecast?field_id={fid}", f"/api/v1/transport/segments?field_id={fid}"):
        r = client.get(path, headers=b["headers"])
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "not_found"
    r = client.patch(f"/api/v1/fields/{fid}", json={"name": "mine now"}, headers=b["headers"])
    assert r.status_code == 404
    assert client.get("/api/v1/fields", headers=b["headers"]).json() == []


def test_fpo_member_cannot_pin(client, db):
    a = login(client, A)
    fpo = Fpo(name="Demo FPO")
    db.add(fpo)
    db.flush()
    db.add(FpoMember(fpo_id=fpo.id, user_id=a["user"]["id"], role="member"))
    db.commit()
    r = client.post(f"/api/v1/fpo/{fpo.id}/posts", json={"kind": "advisory", "title": "t", "body_md": "b", "locale": "mr", "pinned": True},
                    headers=a["headers"])
    assert r.status_code == 403
    r = client.post(f"/api/v1/fpo/{fpo.id}/posts", json={"kind": "question", "title": "t", "body_md": "b", "locale": "mr"}, headers=a["headers"])
    assert r.status_code == 201
    posts = client.get(f"/api/v1/fpo/{fpo.id}/posts", headers=a["headers"]).json()
    assert posts and "phone" not in posts[0]


def test_non_member_cannot_read_fpo(client, db):
    b = login(client, B)
    fpo = Fpo(name="Other FPO")
    db.add(fpo)
    db.commit()
    assert client.get(f"/api/v1/fpo/{fpo.id}/posts", headers=b["headers"]).status_code == 404


def test_future_sowing_date_rejected(client):
    a = login(client, A)
    r = client.post("/api/v1/fields", headers=a["headers"], json={"crop": "mango", "lat": 18.15, "lon": 74.58, "sowing_date": "2099-01-01"})
    assert r.status_code == 400
    assert r.json()["error"]["details"]["field"] == "sowing_date"
