"""Regressions for the 2026-11 UX redesign (docs/UX_QA_AUDIT.md): intent-specific assistant facts (ASK-01..04),
the heavy-rain registry row (REG-01), field delete (FIELDS-01), village search and nearest lookup (ONB-02),
and the dev-outbox delivery hint (FLOW-04). Forecast values are TEST FIXTURE values, no network."""
from datetime import timedelta

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select

from app.core.timeutil import today_ist
from app.models.tables import District, Field, FieldCalibration, ModelRegistry, Taluka, User, Village
from app.services import assistant
from app.services.decision import context as ctx
from app.services.decision import engine
from app.services.voice import intents
from tests.conftest import login
from tests.test_decision import ADVICE, bundle, fake_predict

A, B = "+919876543210", "+919812345678"


@pytest.fixture
def mango_field(db):
    u = User(phone="+919800000001")
    db.add(u)
    db.flush()
    f = Field(user_id=u.id, name="Mango field 1", crop="mango", lat=18.15, lon=74.58, sowing_date=today_ist() - timedelta(days=10))
    db.add(f)
    db.commit()
    return f


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(engine, "_predict", fake_predict)
    monkeypatch.setattr(engine, "transport_risk", lambda db, f, days=7, store=True: ctx.TransportResult(False, "route_unknown"))
    monkeypatch.setattr(engine, "market_summary", lambda db, f, p: None)
    monkeypatch.setattr(engine, "_advisory", lambda db, crop, stage, kind: ADVICE)


def rainy(p_heavy: float, rain_mm: float, tmin: float = 14.0):
    b = bundle(tmin)
    b.days[1].rain_p_heavy = p_heavy
    b.days[1].rain_mm = rain_mm
    return b


def facts(db, f, monkeypatch, question: str, b, loc: str = "en"):
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: b)
    engine.compute(db, f)
    db.commit()
    return assistant._facts_for(db, f, intents.resolve(question), loc)


# ---------- assistant: the answer matches the question ----------
def test_rain_question_without_heavy_rain_risk_never_answers_with_frost(db, mango_field, monkeypatch):
    fs, intro, _ = facts(db, mango_field, monkeypatch, "Will it rain on my mango field?", rainy(0.0, 2.0))
    assert "heavy rain" in intro and "64.5 mm" in intro and "0%" in intro
    assert "°C" not in intro and "temperature" not in intro
    assert all("°C" not in f.value for f in fs)


def test_heavy_rain_risk_is_described_not_reported_as_no_risk(db, mango_field, monkeypatch):
    fs, intro, _ = facts(db, mango_field, monkeypatch, "Will heavy rain come?", rainy(0.6, 82.0))
    assert "No weather risk" not in intro
    assert "60%" in intro and "82 mm" in intro
    assert {f.label for f in fs} >= {"Heavy-rain chance", "Date", "Forecast rain"}


def test_general_weather_question_picks_the_heavy_rain_risk_when_it_is_the_actionable_one(db, mango_field, monkeypatch):
    _, intro, _ = facts(db, mango_field, monkeypatch, "What is the weather forecast?", rainy(0.6, 82.0))
    assert "heavy rain" in intro and "No weather risk" not in intro


def test_frost_question_is_answered_with_frost(db, mango_field, monkeypatch):
    _, intro, _ = facts(db, mango_field, monkeypatch, "Is there frost risk for my mango?", rainy(0.6, 82.0, tmin=3.2))
    assert "lowest temperature" in intro and "3.2 °C" in intro and "rain" not in intro


def test_heat_question_for_a_crop_without_heat_threshold_says_so(db, mango_field, monkeypatch):
    """Mango has no cited heat threshold at this stage: the answer says it is not scored, never quotes frost."""
    th = engine.thresholds_for(mango_field.crop, engine._stage(db, mango_field).stage, ctx.calibration(db, mango_field))
    if th.heat_c is not None:
        pytest.skip("crop table now has a heat threshold for this stage")
    fs, intro, _ = facts(db, mango_field, monkeypatch, "Is it too hot for my mango?", rainy(0.0, 0.0, tmin=3.2))
    assert fs == [] and "not a listed risk" in intro and "Heat" in intro
    assert "°C" not in intro


def test_irrigation_question_gets_no_weather_risk_injected(db, mango_field, monkeypatch):
    fs, intro, _ = facts(db, mango_field, monkeypatch, "How often should I irrigate mango?", rainy(0.6, 82.0, tmin=3.2))
    assert fs == [] and intro is None


def test_stale_weather_is_unavailable_not_no_risk(db, mango_field, monkeypatch):
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(14.0, fetched_ago_h=30))
    engine.compute(db, mango_field)
    db.commit()
    _, intro, _ = assistant._facts_for(db, mango_field, intents.resolve("Will it rain?"), "en")
    assert "out of date" in intro and "No weather risk" not in intro


def test_marathi_rain_answer_is_marathi(db, mango_field, monkeypatch):
    _, intro, _ = facts(db, mango_field, monkeypatch, "पाऊस पडेल का?", rainy(0.6, 82.0), loc="mr")
    assert "मुसळधार" in intro and "64.5" in intro


def test_composed_rain_answer_passes_the_number_validator(db, mango_field, monkeypatch):
    """The fixed constant 64.5 in the template must not trip the composer's number check."""
    from app.services.rag.compose import compose

    fs, intro, _ = facts(db, mango_field, monkeypatch, "Will heavy rain come?", rainy(0.6, 82.0))
    comp = compose("Will heavy rain come?", "en", fs, [ADVICE], intro=intro, require_advice=False,
                   template_constants=assistant.TEMPLATE_CONSTANTS, crop="mango")
    assert not comp.abstain and "64.5 mm" in comp.answer


# ---------- assistant: questions about the field itself (ASK-10) ----------
@pytest.mark.parametrize("question", ["What crop am I growing here", "what is this field", "Help me", "help me please!", "Hello",
                                      "माझ्या शेतात कोणते पीक आहे?", "मदत करा", "मेरे खेत में कौन सी फसल है?", "मदद करो"])
def test_questions_about_the_field_are_not_off_topic(question):
    r = intents.resolve(question)
    assert r.agricultural and r.name == "field_info"


@pytest.mark.parametrize("question", ["Who won the cricket match yesterday?", "help me with my taxes", "Tell me a joke"])
def test_off_topic_questions_stay_off_topic(question):
    assert intents.resolve(question).name == "outside_domain"


def test_a_specific_topic_about_my_field_keeps_its_topic():
    assert intents.resolve("Is there frost risk for my field?").name == "frost"
    assert intents.resolve("What is the mandi price for my crop?").name == "price"


def test_field_summary_comes_from_the_saved_field_and_passes_the_number_validator(db, mango_field, monkeypatch):
    from app.services.rag.compose import compose

    mango_field.area_sqm = 6070.0
    db.commit()
    fs, intro, _ = facts(db, mango_field, monkeypatch, "What crop am I growing here", rainy(0.0, 2.0))
    assert intro.startswith("Mango field 1 is your mango field.")
    assert mango_field.sowing_date.isoformat() in intro and "0.61 ha" in intro
    labels = {f.label: f.value for f in fs}
    assert labels["Crop"] == "mango" and labels["Field"] == "Mango field 1" and labels["Area"] == "0.61 ha"
    assert "No weather risk for your mango in the next 3 days." in intro  # today's check for this field
    comp = compose("What crop am I growing here", "en", fs, [], intro=intro, require_advice=False,
                   template_constants=assistant.TEMPLATE_CONSTANTS, crop="mango")
    assert not comp.abstain and comp.answer.startswith("Mango field 1 is your mango field.")


def test_field_summary_without_sowing_date_asks_for_it(db, mango_field, monkeypatch):
    mango_field.sowing_date = None
    db.commit()
    fs, intro, _ = facts(db, mango_field, monkeypatch, "what is this field", rainy(0.0, 2.0))
    assert "Add the sowing date" in intro
    assert "Crop stage" not in {f.label for f in fs}


def test_marathi_field_summary_is_marathi(db, mango_field, monkeypatch):
    _, intro, _ = facts(db, mango_field, monkeypatch, "माझ्या शेतात कोणते पीक आहे?", rainy(0.0, 2.0), loc="mr")
    assert "आंबा शेत आहे" in intro


# ---------- assistant: the model gets the whole farmer, keywords no longer refuse it (ASK-13) ----------
@pytest.mark.parametrize("question,intent", [
    ("What is growin here", "field_info"),
    ("I am literally asking you what am I growing in my G spot field", "field_info"),
    ("When did I prune it and how big is it?", "field_info"),
    ("what is my name", "profile"),
    ("where is my farm", "profile"),
    ("मेरे खेत में क्या उगा है?", "field_info"),
])
def test_typos_follow_ups_and_account_questions_are_placed(question, intent):
    assert intents.resolve(question).name == intent


def test_a_question_naming_my_own_field_or_variety_is_about_the_field(db, mango_field):
    mango_field.variety = "Kesar"
    db.commit()
    u = db.get(User, mango_field.user_id)
    assert assistant._names_own_field(db, u, "How is kesar doing?")
    assert assistant._names_own_field(db, u, "anything new on Mango field 1")
    assert not assistant._names_own_field(db, u, "Who won the cricket match yesterday?")


@pytest.fixture
def ask_env(db, mango_field, monkeypatch):
    b = rainy(0.0, 2.0)
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: b)
    monkeypatch.setattr(assistant.rag, "search", lambda *a, **k: [])
    u = db.get(User, mango_field.user_id)
    u.name = "Test Farmer"
    db.commit()
    return u


def test_without_the_model_an_unplaced_question_is_refused(db, mango_field, ask_env, monkeypatch):
    monkeypatch.setattr(assistant, "groq_enabled", lambda: False)
    r = assistant.ask(db, ask_env, "Tell me a joke", None, mango_field.id, "en")
    assert r["abstain"] and r["abstain_reason"] == "outside_domain"


def test_with_the_model_an_unplaced_question_goes_to_it_with_the_whole_farmer(db, mango_field, ask_env, monkeypatch):
    from app.services.llm import grounded

    seen = {}

    def fake(messages):
        seen["messages"] = messages
        return "Hello Test Farmer, your Mango field 1 is at flowering."
    monkeypatch.setattr(assistant, "groq_enabled", lambda: True)
    monkeypatch.setattr(grounded, "chat_completion", fake)
    r = assistant.ask(db, ask_env, "Tell me something nice", None, mango_field.id, "en",
                      history=[{"role": "user", "content": "What is growing here?"}])
    assert not r["abstain"] and r["answer_source"] == "groq" and r["answer"].startswith("Hello Test Farmer")
    ctx = seen["messages"][-1]["content"]
    assert '"name": "Test Farmer"' in ctx and "Mango field 1" in ctx and '"selected": true' in ctx
    assert "+9198" not in ctx and '"lat"' not in ctx  # no phone number or raw coordinates
    assert seen["messages"][1] == {"role": "user", "content": "What is growing here?"}


def test_the_model_saying_off_topic_is_a_refusal(db, mango_field, ask_env, monkeypatch):
    from app.services.llm import grounded

    monkeypatch.setattr(assistant, "groq_enabled", lambda: True)
    monkeypatch.setattr(grounded, "chat_completion", lambda messages: "OUTSIDE_DOMAIN")
    r = assistant.ask(db, ask_env, "Tell me a joke", None, mango_field.id, "en")
    assert r["abstain"] and r["abstain_reason"] == "outside_domain"


def test_the_model_unavailable_for_an_unplaced_question_is_a_refusal_not_a_guess(db, mango_field, ask_env, monkeypatch):
    from app.services.llm import grounded

    monkeypatch.setattr(assistant, "groq_enabled", lambda: True)
    monkeypatch.setattr(grounded, "chat_completion", lambda messages: None)
    r = assistant.ask(db, ask_env, "Tell me a joke", None, mango_field.id, "en")
    assert r["abstain_reason"] == "outside_domain"


def test_profile_answer_without_the_model(db, mango_field, ask_env, monkeypatch):
    monkeypatch.setattr(assistant, "groq_enabled", lambda: False)
    r = assistant.ask(db, ask_env, "what is my name", None, mango_field.id, "en")
    assert not r["abstain"] and r["answer"].startswith("Your name in FasalAlert is Test Farmer.")
    assert "Mango field 1 (mango" in r["answer"]


def test_model_numbers_are_compared_by_value_and_get_one_correction(monkeypatch):
    from app.services.llm import grounded

    monkeypatch.setattr(grounded, "chat_completion", lambda messages: "The field covers 4 hectares.")
    assert grounded.draft_answer('{"area": {"hectares": 4.0}}', "en", "How big is it?", set()) == "The field covers 4 hectares."
    replies = iter(["Apply 999 kg tonight.", "Apply the dose on the label."])
    calls = []

    def fake(messages):
        calls.append(messages)
        return next(replies)
    monkeypatch.setattr(grounded, "chat_completion", fake)
    assert grounded.draft_answer('{"x": 1}', "en", "How much?", set()) == "Apply the dose on the label."
    assert len(calls) == 2 and "999" in calls[1][-1]["content"]


def test_farmer_context_holds_the_account_and_every_field(db, mango_field, ask_env):
    import json as _json

    from app.services.llm.farmer import farmer_context

    mango_field.area_sqm = 40000.0
    mango_field.variety = "Kesar"
    db.commit()
    ctx = farmer_context(db, ask_env, mango_field, "en")
    f = ctx["fields"][0]
    assert ctx["farmer"]["name"] == "Test Farmer" and ctx["farmer"]["number_of_fields"] == 1
    assert f["name"] == "Mango field 1" and f["selected"] and f["variety"] == "Kesar" and f["crop"] == "mango"
    assert f["area"]["hectares"] == 4 and f["season_start_kind"] == "sowing or planting" and f["stage"]["now"]
    assert "phone" not in _json.dumps(ctx["farmer"]) and "lat" not in f


# ---------- model registry ----------
def test_every_served_rule_version_has_a_registry_row(db):
    from app.services.models import phenology, rain, transport
    from app.services.models.registry import register_static

    register_static(db)
    db.commit()
    rows = {(r.name, r.version) for r in db.execute(select(ModelRegistry)).scalars()}
    assert ("rain", rain.VERSION) in rows
    assert ("transport", transport.VERSION) in rows and ("phenology", phenology.VERSION) in rows


def test_heavy_rain_risk_uses_the_registered_version(db, mango_field, monkeypatch):
    from app.services.models import rain

    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: rainy(0.6, 82.0))
    d = engine.compute(db, mango_field)
    r = next(x for x in d["risks"] if x["kind"] == "heavy_rain")
    assert r["model_version"] == rain.VERSION
    if not d.get("abstain_reason"):   # the fixture advisory is about frost, so the engine may abstain here
        assert d["model_versions"]["rain"] == rain.VERSION
    assert d["checks"]["rain"]["evaluated"] is True and d["checks"]["rain"]["max_p_heavy"] == 0.6


# ---------- fields ----------
def _field(db, user_id):
    f = Field(user_id=user_id, name="Mango field 1", crop="mango", lat=18.15, lon=74.58, sowing_date=today_ist() - timedelta(days=10))
    db.add(f)
    db.flush()
    ctx.calibration(db, f)
    db.commit()
    return f.id


def test_delete_own_field_removes_it_and_its_children(client, db):
    a = login(client, A)
    fid = _field(db, a["user"]["id"])
    r = client.delete(f"/api/v1/fields/{fid}", headers=a["headers"])
    assert r.status_code == 204
    assert client.get(f"/api/v1/fields/{fid}", headers=a["headers"]).status_code == 404
    db.expire_all()
    assert db.get(FieldCalibration, fid) is None


def test_cannot_delete_another_users_field(client, db):
    a, b = login(client, A), login(client, B)
    fid = _field(db, a["user"]["id"])
    r = client.delete(f"/api/v1/fields/{fid}", headers=b["headers"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    db.expire_all()
    assert db.get(Field, fid) is not None


def test_delete_needs_sign_in(client, db):
    assert client.delete("/api/v1/fields/1").status_code == 401


# ---------- locations ----------
@pytest.fixture
def geo(db):
    d = District(code="MH-TEST", name_en="Testpur", name_mr="टेस्टपूर", name_hi="टेस्टपुर", centroid=from_shape(Point(74.6, 18.2), srid=4326))
    db.add(d)
    db.flush()
    t = Taluka(district_id=d.id, code="MH-TEST-T1", name_en="Baramati Test", name_mr="बारामती टेस्ट", name_hi="बारामती टेस्ट",
               centroid=from_shape(Point(74.58, 18.15), srid=4326))
    db.add(t)
    db.flush()
    db.add_all([Village(taluka_id=t.id, name_en="Malegaon Kh.", name_mr="माळेगाव खु.", name_hi="मालेगांव खु.", lat=18.15, lon=74.58),
                Village(taluka_id=t.id, name_en="Shirsufal", name_mr="शिर्सुफळ", name_hi="शिर्सुफल", lat=18.30, lon=74.70)])
    db.commit()
    return d, t


def test_village_search_matches_english_and_marathi_names(client, geo):
    r = client.get("/api/v1/locations/search", params={"q": "male"})
    assert r.status_code == 200
    hits = r.json()
    assert [h["name"]["en"] for h in hits] == ["Malegaon Kh."]
    assert hits[0]["taluka"]["name"]["en"] == "Baramati Test" and hits[0]["district"]["name"]["mr"] == "टेस्टपूर"
    assert client.get("/api/v1/locations/search", params={"q": "शिर्सु"}).json()[0]["name"]["en"] == "Shirsufal"
    assert client.get("/api/v1/locations/search", params={"q": "m"}).status_code == 400


def test_nearest_village_for_a_gps_point(client, geo):
    r = client.get("/api/v1/locations/nearest", params={"lat": 18.16, "lon": 74.59})
    assert r.status_code == 200
    body = r.json()
    assert body["village"]["name"]["en"] == "Malegaon Kh." and body["district"]["id"] == geo[0].id
    assert 0 < body["distance_km"] < 2


def test_nearest_village_far_from_every_village_is_not_found(client, geo):
    r = client.get("/api/v1/locations/nearest", params={"lat": 21.5, "lon": 79.5})
    assert r.status_code == 404


# ---------- sign-in delivery hint ----------
def test_otp_request_returns_demo_code_only_when_demo_otp_is_enabled(client):
    phone = "+919700000101"
    r = client.post("/api/v1/auth/otp/request", json={"phone": phone})
    body = r.json()
    assert r.status_code == 200 and body["delivery"] == "dev_outbox"
    assert "code" not in body  # never use the production field name
    assert body["demo_code"] and len(body["demo_code"]) == 6 and body["demo_code"].isdigit()
    # The demo_code must be the same value the server accepts on verify.
    v = client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": body["demo_code"]})
    assert v.status_code == 200


def test_otp_request_hides_demo_code_when_flag_is_off(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("DEMO_OTP_VISIBLE", "false")
    get_settings.cache_clear()
    try:
        r = client.post("/api/v1/auth/otp/request", json={"phone": "+919700000102"})
        body = r.json()
        assert r.status_code == 200 and body["delivery"] == "dev_outbox"
        assert "demo_code" not in body and "code" not in body
    finally:
        monkeypatch.delenv("DEMO_OTP_VISIBLE", raising=False)
        get_settings.cache_clear()


def test_decisions_today_does_not_recompute_a_field_already_being_computed(client, db, monkeypatch):
    """HOME-02: a new field's first decision runs in a background task; /decisions/today must not run it again."""
    from app.routers import fields as fields_router

    a = login(client, A)
    fid = _field(db, a["user"]["id"])
    fields_router.PENDING_RECOMPUTE.add(fid)
    try:
        monkeypatch.setattr(engine, "compute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("computed twice")))
        r = client.get("/api/v1/decisions/today", headers=a["headers"])
        assert r.status_code == 200 and r.json() == []
    finally:
        fields_router.PENDING_RECOMPUTE.discard(fid)


def test_mandis_accept_the_crop_key_the_web_app_sends(client, db):
    """MKT-02: the web app asks for commodity=grape; mandis are stored under the AGMARKNET name "Grapes"."""
    from app.models.tables import MandiMarket

    a = login(client, A)
    fid = _field(db, a["user"]["id"])
    f = db.get(Field, fid)
    f.crop = "grape"
    db.add(MandiMarket(name="Lasalgaon", commodity="Grapes", lat=20.15, lon=74.23))
    db.commit()
    r = client.get("/api/v1/market/mandis", params={"commodity": "grape", "field_id": fid}, headers=a["headers"])
    assert r.status_code == 200 and [m["name"] for m in r.json()] == ["Lasalgaon"]
    r = client.get("/api/v1/market/mandis", params={"commodity": "Grapes", "field_id": fid}, headers=a["headers"])
    assert [m["name"] for m in r.json()] == ["Lasalgaon"]


def test_field_list_never_computes_a_gdd_stage_inline(client, db, monkeypatch):
    """API-03: GET /fields must not fetch weather history for a field whose first decision is not stored yet."""
    a = login(client, A)
    f = Field(user_id=a["user"]["id"], name="Soybean field 1", crop="soybean", lat=20.0, lon=74.0, sowing_date=today_ist() - timedelta(days=30))
    db.add(f)
    db.commit()
    from app.services.models import phenology

    if phenology.crop_info("soybean")["phenology"]["method"] != "gdd":
        pytest.skip("soybean is not a GDD crop in the crop table")
    monkeypatch.setattr(engine, "_stage", lambda *a, **k: (_ for _ in ()).throw(AssertionError("stage computed inline")))
    r = client.get("/api/v1/fields", headers=a["headers"])
    assert r.status_code == 200
    st = r.json()[0]["stage"]
    assert st["stage"] is None and "worked out" in st["explanation"]["en"]


def test_a_route_saved_by_a_parallel_request_is_reused_not_a_500(db, monkeypatch):
    """API-04: two requests routing the same field at once; the second insert conflicts and must reuse the row."""
    from app.core.db import SessionLocal
    from app.models.tables import FieldRoute
    from app.services.foundry.roads import Route

    u = User(phone="+919800000002")
    db.add(u)
    db.flush()
    f = Field(user_id=u.id, name="Cotton field 1", crop="cotton", lat=18.15, lon=74.58)
    db.add(f)
    db.commit()
    monkeypatch.setattr(ctx, "_mandi_ll", lambda db, f: ("Baramati", 18.15, 74.58))

    def parallel_request_wins(a, b):
        other = SessionLocal()
        other.add(FieldRoute(field_id=f.id, market_name="Baramati", segment_ids=[], route_name="won", source="test"))
        other.commit()
        other.close()
        return Route(distance_km=10.0, duration_min=15.0, name="NH", segments=[])

    monkeypatch.setattr(ctx, "fetch_route", parallel_request_wins)
    monkeypatch.setattr(ctx, "attach_elevation", lambda r: None)
    route = ctx.ensure_route(db, f)
    assert route is not None and route.route_name == "won"


def test_field_history_confirms_an_outcome_against_a_stored_observation(client, db, monkeypatch):
    """API-05: the history endpoint compared a DATE column with the payload's ISO string and failed with a 500."""
    from datetime import date as _date

    from app.models.tables import WeatherObservation

    a = login(client, A)
    fid = _field(db, a["user"]["id"])
    f = db.get(Field, fid)
    monkeypatch.setattr(engine, "get_forecast", lambda db, lat, lon, field_id=None, force=False: bundle(3.2))
    d = engine.compute(db, f)
    db.commit()
    frost = next(r for r in d["risks"] if r["kind"] == "frost")
    ev = frost["evidence"]["event_date"]
    db.add(WeatherObservation(station_id=f"g{round(f.lat, 1):.1f}_{round(f.lon, 1):.1f}", lat=f.lat, lon=f.lon, obs_date=_date.fromisoformat(ev),
                              tmin_c=2.0, tmax_c=29.0, source="test"))
    db.commit()
    r = client.get(f"/api/v1/fields/{fid}/decisions", headers=a["headers"])
    assert r.status_code == 200, r.text
    out = r.json()[0]["outcome"]
    assert out["status"] == "confirmed" and out["observed_value_c"] == 2.0 and out["observed_on"] == ev


def test_preferences_say_when_sms_only_goes_to_the_dev_outbox(client):
    """ALR-01: in development an SMS "delivery" is a file line; the app must be able to say so."""
    a = login(client, A)
    prefs = client.get("/api/v1/users/me", headers=a["headers"]).json()["preferences"]
    assert prefs["sms_dev_outbox"] is True
