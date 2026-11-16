"""End-to-end API journey (build brief Part 15) against live public services. Marked `network`.

Run: uv run pytest -m network tests/test_journey.py
Steps: public board -> OTP sign-in -> create field -> weather -> phenology -> risks -> retrieval -> decision ->
home -> field detail -> ask in Marathi (text; audio needs Bhashini) -> market -> transport.
"""
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.timeutil import today_ist
from app.models.tables import AdvisoryChunk, District
from tests.conftest import login

pytestmark = pytest.mark.network


@pytest.fixture
def seeded(db):
    """Use the real seed when the geo data is present in the test database; otherwise seed it from the repo files."""
    if db.execute(select(func.count()).select_from(District)).scalar_one() == 0:
        import subprocess
        import sys

        r = subprocess.run([sys.executable, "scripts/seed_locations.py"], capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            pytest.skip(f"geo seed unavailable: {r.stderr[-300:]}")
    return db


def test_full_journey(client, seeded):
    db = seeded
    # 1. anonymous public board
    board = client.get("/api/v1/public/risks")
    assert board.status_code in (200, 503), board.text
    if board.status_code == 200:
        b = board.json()
        assert len(b["districts"]) == db.execute(select(func.count()).select_from(District)).scalar_one()
        for d in b["districts"]:
            if d["level"] not in ("nodata", "none") and d["reason"]:
                assert "°C" in d["reason"]["en"]          # AC 18: reason cites a threshold
    # 2. sign in with OTP
    me = login(client)
    h = me["headers"]
    # 3 to 5. create a mango field near Baramati with its season start (flowering) 20 days ago
    district = db.execute(text("select id from districts where name_en ilike 'pune' limit 1")).scalar()
    r = client.post("/api/v1/fields", headers=h, json={"crop": "mango", "variety": "alphonso", "lat": 18.1515, "lon": 74.5815,
                                                       "district_id": district, "sowing_date": (today_ist() - timedelta(days=20)).isoformat()})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert r.json()["stage"]["stage"] == "flowering"   # 7. phenology
    # 6. weather
    w = client.get(f"/api/v1/weather/forecast?field_id={fid}", headers=h)
    assert w.status_code == 200 and w.json()["rows"] and w.json()["rows"][0]["source"] == "open-meteo"
    # 8 to 11. risks, retrieval and the decision on Home
    today = client.get("/api/v1/decisions/today?locale=mr", headers=h)
    assert today.status_code == 200, today.text
    dec = today.json()[0]
    assert dec["field_id"] == fid
    assert dec["abstain_reason"] is None, dec["abstain_reason"]    # live forecast + frost artifact: no reason to abstain
    assert dec["sources"] and dec["model_versions"]["frost"].startswith("frost-")
    frost = next(r for r in dec["risks"] if r["kind"] == "frost")  # mango flowering has a 4.4 °C frost threshold
    assert frost["evidence"]["method"] == "model" and frost["evidence"]["calibrated"] is True
    assert frost["lead_hours"] > 0 and frost["band_low_c"] <= frost["tmin_c"] <= frost["band_high_c"]
    path = {"board": board.status_code, "frost_method": frost["evidence"]["method"],
            "forecast_model": frost["evidence"].get("forecast_model")}
    # 12. field detail
    det = client.get(f"/api/v1/fields/{fid}?locale=mr", headers=h)
    assert det.status_code == 200 and det.json()["last_decision"]["field_id"] == fid
    # 13 to 16. ask in Marathi
    ask = client.post("/api/v1/ask", headers=h, json={"text": "माझ्या आंब्याला दंवाचा धोका आहे का?", "locale": "mr", "field_id": fid})
    assert ask.status_code == 200, ask.text
    a = ask.json()
    has_corpus = db.execute(select(func.count()).select_from(AdvisoryChunk).where(AdvisoryChunk.verified)).scalar_one() > 0
    assert a["answer"]
    if a["abstain"]:
        assert a["kvk"]["phone"]
    else:
        assert has_corpus and any(s.get("kind") == "advisory" for s in a["sources"])
    path.update({"corpus_chunks_in_test_db": has_corpus, "ask_abstained": a["abstain"]})
    # 18. market and transport
    m = client.get(f"/api/v1/market/mandis?commodity=Mango&field_id={fid}", headers=h)
    assert m.status_code == 200
    t = client.get(f"/api/v1/transport/risk?field_id={fid}", headers=h)
    assert t.status_code == 200 and "not from observed closures" in t.json()["note"]
    if t.json()["available"]:
        assert len(t.json()["days"]) == 7
    path.update({"mandis": len(m.json().get("mandis", m.json()) if isinstance(m.json(), dict) else m.json()),
                 "transport_available": t.json()["available"]})
    print("JOURNEY", path)
