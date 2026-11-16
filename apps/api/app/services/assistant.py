"""Ask pipeline (PRD §7.5): STT -> intent -> field facts from models -> verified retrieval -> answer -> TTS.

When GROQ_API_KEY is set, a Qwen model on Groq drafts the spoken answer from grounded field + RAG
context (numbers are still validated). Without a key, composition stays fully deterministic.
"""
from __future__ import annotations

import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.timeutil import iso, now_utc, today_ist
from app.models.tables import DecisionRow, District, Field, Taluka, User, Village
from app.security.deps import ASK_DAILY_LIMIT, asks_used_today, audit, owned_field
from app.services.decision import engine
from app.services.decision.context import fallback_contact, kvk_for, market_summary, transport_risk
from app.services.llm.groq import groq_enabled
from app.services.llm.grounded import OUTSIDE, allowed_number_tokens, build_context, draft_answer
from app.services.rag import retrieve as rag
from app.services.rag.compose import Fact, compose
from app.services.rag.vocab import alias_index
from app.services.voice import intents, speech

log = logging.getLogger("fasalalert.assistant")

TOPIC_FOR = {"frost": "frost_protection", "heat": "heat_stress", "rain": "rainfall_management", "irrigation": "irrigation",
             "pest_disease": "pest_disease", "harvest": "harvesting", "stage": "growth_stage", "transport": "transport"}
NEEDS_ADVICE = {"frost", "heat", "rain", "irrigation", "pest_disease", "harvest", "action", "advisory"}
UNSURE = 0.6


def _src(label: str, url: str | None, at: str | None, kind: str) -> dict[str, Any]:
    return {"label": label, "url": url, "fetched_at": at, "kind": kind}


def _pick_field(db: Session, user: User, field_id: int | None, intent: intents.Intent) -> Field | None:
    if field_id is not None:
        return owned_field(db, user, field_id)
    fields = db.execute(select(Field).where(Field.user_id == user.id).order_by(Field.id)).scalars().all()
    if intent.crops:
        for f in fields:
            if f.crop in intent.crops:
                return f
    return fields[0] if fields else None


def _decision(db: Session, f: Field) -> dict[str, Any]:
    """Today's decision, or {} when the engine cannot produce one (the answer then relies on advice only)."""
    row = db.execute(select(DecisionRow).where(DecisionRow.field_id == f.id, DecisionRow.decision_date == today_ist())).scalar_one_or_none()
    if row:
        return row.payload
    try:
        with db.begin_nested():
            return engine.compute(db, f)
    except Exception:  # noqa: BLE001 - degrade the feature, not the answer (PRD §13 rule 2)
        import logging

        logging.getLogger("fasalalert.assistant").exception("decision unavailable for field %s", f.id)
        return {}


T = {
    "risk_frost": {"en": "For your {crop}: the lowest temperature forecast is {value} on {date}; the {stage} threshold is {thr}; chance of going below it {p}.",
                   "mr": "तुमच्या {crop} पिकासाठी: {date} रोजी किमान तापमानाचा अंदाज {value}; {stage} मर्यादा {thr}; तापमान त्याखाली जाण्याची शक्यता {p}.",
                   "hi": "आपकी {crop} फसल के लिए: {date} को न्यूनतम तापमान का पूर्वानुमान {value}; {stage} सीमा {thr}; तापमान उससे नीचे जाने की संभावना {p}."},
    "risk_heat": {"en": "For your {crop}: the highest temperature forecast is {value} on {date}; the {stage} threshold is {thr}; chance of going above it {p}.",
                  "mr": "तुमच्या {crop} पिकासाठी: {date} रोजी कमाल तापमानाचा अंदाज {value}; {stage} मर्यादा {thr}; तापमान ती ओलांडण्याची शक्यता {p}.",
                  "hi": "आपकी {crop} फसल के लिए: {date} को अधिकतम तापमान का पूर्वानुमान {value}; {stage} सीमा {thr}; तापमान उसके पार जाने की संभावना {p}."},
    "stage_generic": {"en": "crop", "mr": "पिकाची", "hi": "फसल की"},
    "rain": {"en": "For your {crop}: the chance of heavy rain (64.5 mm or more in a day) on {date} is {p}.",
             "mr": "तुमच्या {crop} पिकासाठी: {date} रोजी मुसळधार पावसाची (एका दिवसात 64.5 मिमी किंवा अधिक) शक्यता {p}.",
             "hi": "आपकी {crop} फसल के लिए: {date} को भारी बारिश (एक दिन में 64.5 मिमी या अधिक) की संभावना {p}."},
    "rain_mm": {"en": " Forecast rain that day: {mm}.", "mr": " त्या दिवशी अंदाजे पाऊस: {mm}.", "hi": " उस दिन अनुमानित बारिश: {mm}."},
    "rain_none": {"en": "For your {crop}: no heavy rain (64.5 mm or more in a day) is expected in the next {days} days; the highest chance is {p}.",
                  "mr": "तुमच्या {crop} पिकासाठी: पुढील {days} दिवसांत मुसळधार पाऊस (एका दिवसात 64.5 मिमी किंवा अधिक) अपेक्षित नाही; सर्वाधिक शक्यता {p}.",
                  "hi": "आपकी {crop} फसल के लिए: अगले {days} दिनों में भारी बारिश (एक दिन में 64.5 मिमी या अधिक) अपेक्षित नहीं; सबसे अधिक संभावना {p}."},
    "rain_unavailable": {"en": "The heavy-rain chance for your {crop} field is not available right now: the ensemble forecast is missing.",
                         "mr": "तुमच्या {crop} शेतासाठी मुसळधार पावसाची शक्यता सध्या उपलब्ध नाही: एन्सेम्बल अंदाज मिळालेला नाही.",
                         "hi": "आपके {crop} खेत के लिए भारी बारिश की संभावना अभी उपलब्ध नहीं है: एन्सेम्बल पूर्वानुमान नहीं मिला."},
    "not_scored": {"en": "{kind} is not a listed risk for your {crop} at this stage, so FasalAlert does not score it now.",
                   "mr": "या अवस्थेत तुमच्या {crop} पिकासाठी {kind} हा नोंदलेला धोका नाही, म्हणून FasalAlert सध्या त्याचा अंदाज देत नाही.",
                   "hi": "इस अवस्था में आपकी {crop} फसल के लिए {kind} सूचीबद्ध खतरा नहीं है, इसलिए FasalAlert अभी इसका अनुमान नहीं देता."},
    "kind_unavailable": {"en": "I could not check the {kind} risk for your {crop} right now. Please try again later.",
                         "mr": "तुमच्या {crop} पिकासाठी {kind} धोका सध्या तपासता आला नाही. कृपया नंतर पुन्हा प्रयत्न करा.",
                         "hi": "आपकी {crop} फसल के लिए {kind} खतरा अभी जांचा नहीं जा सका. कृपया बाद में फिर कोशिश करें."},
    "wx_stale": {"en": "The weather data for your field is out of date, so I cannot answer about the weather right now.",
                 "mr": "तुमच्या शेताची हवामान माहिती जुनी आहे, त्यामुळे सध्या हवामानाबद्दल सांगता येत नाही.",
                 "hi": "आपके खेत की मौसम जानकारी पुरानी है, इसलिए अभी मौसम के बारे में नहीं बता सकते."},
    "wx_unavailable": {"en": "I cannot check the weather for your {crop} right now.", "mr": "तुमच्या {crop} पिकासाठी सध्या हवामान तपासता येत नाही.",
                       "hi": "आपकी {crop} फसल के लिए अभी मौसम नहीं जांच सकते."},
    "need_sowing": {"en": "Add the sowing date for your {crop} so I can work out the crop stage and its weather limits.",
                    "mr": "पिकाची अवस्था व हवामान मर्यादा ठरवण्यासाठी तुमच्या {crop} पिकाची पेरणीची तारीख भरा.",
                    "hi": "फसल की अवस्था और मौसम सीमा तय करने के लिए अपनी {crop} फसल की बुवाई की तारीख भरें."},
    "no_temp_risk": {"en": "No frost or heat risk for your {crop} in the next 3 days; the heavy-rain chance is not available.",
                     "mr": "पुढील 3 दिवसांत तुमच्या {crop} पिकाला दंव किंवा उष्णतेचा धोका नाही; मुसळधार पावसाची शक्यता उपलब्ध नाही.",
                     "hi": "अगले 3 दिनों में आपकी {crop} फसल को पाले या गर्मी का खतरा नहीं; भारी बारिश की संभावना उपलब्ध नहीं."},
    "no_risk": {"en": "No weather risk for your {crop} in the next 3 days.", "mr": "पुढील 3 दिवसांत तुमच्या {crop} पिकाला हवामानाचा धोका नाही.",
                "hi": "अगले 3 दिनों में आपकी {crop} फसल को मौसम का कोई खतरा नहीं."},
    "price": {"en": "{market} {commodity}: modal price {price} on {date}.", "mr": "{market} {commodity}: {date} रोजी सरासरी भाव {price}.",
              "hi": "{market} {commodity}: {date} को औसत भाव {price}."},
    "price_fc": {"en": " Median forecast {p50}, likely range {p10} to {p90}.", "mr": " अंदाजे मध्य भाव {p50}, संभाव्य फरक {p10} ते {p90}.",
                 "hi": " अनुमानित मध्य भाव {p50}, संभावित दायरा {p10} से {p90}."},
    "route": {"en": "{route}: risk from rainfall and terrain {p} in the next 3 days.", "mr": "{route}: पुढील 3 दिवसांत पाऊस व भूभागामुळे धोका {p}.",
              "hi": "{route}: अगले 3 दिनों में बारिश और भू-भाग से खतरा {p}."},
    "deadline": {"en": " Load by {date}.", "mr": " {date} पर्यंत माल भरा.", "hi": " {date} तक माल लादें."},
    "skill_caveat": {"en": " Early estimate: accuracy at this threshold is not yet shown.",
                     "mr": " प्राथमिक अंदाज: या मर्यादेवरची अचूकता अजून सिद्ध झालेली नाही.",
                     "hi": " प्रारंभिक अनुमान: इस सीमा पर सटीकता अभी साबित नहीं हुई है."},
    "stage": {"en": "Your {crop} is at {stage}.", "mr": "तुमचे {crop} पीक {stage} अवस्थेत आहे.", "hi": "आपकी {crop} फसल {stage} अवस्था में है."},
    "no_field": {"en": "Add a field first so I can answer about your crop.", "mr": "आधी शेत जोडा, म्हणजे मी तुमच्या पिकाबद्दल सांगू शकेन.",
                 "hi": "पहले खेत जोड़ें, ताकि मैं आपकी फसल के बारे में बता सकूं."},
    "outside": {"en": "I can only help with farming questions about your fields.", "mr": "मी फक्त तुमच्या शेताबद्दलच्या शेती प्रश्नांना मदत करू शकतो.",
                "hi": "मैं केवल आपके खेत से जुड़े खेती के सवालों में मदद कर सकता हूं."},
    "profile_name": {"en": "Your name in FasalAlert is {name}.", "mr": "FasalAlert मधील तुमचे नाव {name} आहे.",
                     "hi": "FasalAlert में आपका नाम {name} है।"},
    "profile_no_name": {"en": "You have not added your name yet; you can add it in Settings.",
                        "mr": "तुम्ही अजून नाव भरलेले नाही; ते सेटिंग्जमध्ये भरता येईल.",
                        "hi": "आपने अभी नाम नहीं भरा है; इसे सेटिंग्स में भर सकते हैं।"},
    "profile_fields": {"en": " Your fields ({count}): {list}.", "mr": " तुमची शेते ({count}): {list}.", "hi": " आपके खेत ({count}): {list}।"},
    "field_name": {"en": "{name} is your {crop} field", "mr": "{name} हे तुमचे {crop} शेत आहे", "hi": "{name} आपका {crop} खेत है"},
    "field_place": {"en": " in {place}", "mr": " ({place})", "hi": " ({place})"},
    "field_end": {"en": ".", "mr": ".", "hi": "।"},
    "field_sown": {"en": " Sown on {date}.", "mr": " पेरणी {date} रोजी.", "hi": " बुवाई {date} को।"},
    "field_pruned": {"en": " Fruit pruning on {date}.", "mr": " फळछाटणी {date} रोजी.", "hi": " फल छंटाई {date} को।"},
    "field_variety": {"en": " Variety {variety}.", "mr": " वाण {variety}.", "hi": " किस्म {variety}।"},
    "field_area": {"en": " Area {area}.", "mr": " क्षेत्र {area}.", "hi": " क्षेत्रफल {area}।"},
    "field_no_sowing": {"en": " Add the sowing date so I can work out the crop stage.", "mr": " पिकाची अवस्था ठरवण्यासाठी पेरणीची तारीख भरा.",
                        "hi": " फसल की अवस्था तय करने के लिए बुवाई की तारीख भरें।"},
    "field_more": {"en": " You can ask me about frost, heat, rain, pests, mandi prices or the road to the mandi.",
                   "mr": " दंव, उष्णता, पाऊस, कीड, बाजारभाव किंवा बाजाराचा रस्ता याबद्दल विचारा.",
                   "hi": " पाला, गर्मी, बारिश, कीट, मंडी भाव या मंडी के रास्ते के बारे में पूछें।"},
    "abstain": {"en": "I do not have verified advice for this. Please call {kvk}.", "mr": "याबद्दल माझ्याकडे खात्रीशीर सल्ला नाही. कृपया {kvk} ला फोन करा.",
                "hi": "इसके लिए मेरे पास प्रमाणित सलाह नहीं है. कृपया {kvk} को फ़ोन करें."},
    "no_market": {"en": "No market price is available for your crop yet.", "mr": "तुमच्या पिकाचा बाजारभाव अजून उपलब्ध नाही.",
                  "hi": "आपकी फसल का बाज़ार भाव अभी उपलब्ध नहीं है."},
    "no_route": {"en": "The route from your field to the market is not known, so I cannot estimate road risk.",
                 "mr": "शेतापासून बाजारापर्यंतचा मार्ग माहीत नाही, त्यामुळे रस्त्याचा धोका सांगता येत नाही.",
                 "hi": "खेत से बाज़ार तक का रास्ता ज्ञात नहीं, इसलिए सड़क का खतरा नहीं बता सकते."},
}


def _t(key: str, loc: str, **kw: Any) -> str:
    return T[key][loc].format(**kw)


def _stage_label(crop: str, stage: str | None, loc: str) -> str:
    """The stage name in the reader's language (crops.json labels), never the internal key."""
    from app.services.models import phenology

    for st in phenology.crop_info(crop)["phenology"]["stages"]:
        if st["key"] == stage:
            label = st["label"].get(loc) or st["label"]["en"]
            return label.lower() if loc == "en" else label
    return ""


def _pct(p: float) -> str:
    return f"{round(p * 100)}%"


def _facts_for(db: Session, f: Field, intent: intents.Intent, loc: str) -> tuple[list[Fact], str | None, dict[str, Any] | None]:
    crop = engine.CROP_NAMES[loc][f.crop]
    d = _decision(db, f)
    facts: list[Fact] = []
    intro = None
    name = intent.name
    if name in ("price",):
        tr = transport_risk(db, f, store=False)
        m = market_summary(db, f, tr.p72 if tr.available else None)
        if not m:
            return [], _t("no_market", loc), d
        src = _src(f"AGMARKNET {m['market']}" if m["source"] != "synthetic_seed" else "Synthetic sample, not real prices",
                   "https://agmarknet.gov.in" if m["source"] != "synthetic_seed" else None, m["price_date"],
                   "synthetic" if m["source"] == "synthetic_seed" else "market")
        price = f"₹{round(m['modal_rs_qtl'])}/qtl"
        facts += [Fact("Modal price", price, src), Fact("Price date", m["price_date"], src)]
        intro = _t("price", loc, market=m["market"], commodity=crop, price=price, date=m["price_date"])
        if m.get("forecast_available") and m.get("forecast_p50"):
            msrc = _src("FasalAlert price model", None, iso(now_utc()), "model")
            facts += [Fact("Forecast median", f"₹{m['forecast_p50']}", msrc), Fact("Forecast low", f"₹{m['forecast_p10']}", msrc),
                      Fact("Forecast high", f"₹{m['forecast_p90']}", msrc)]
            intro += _t("price_fc", loc, p50=f"₹{m['forecast_p50']}", p10=f"₹{m['forecast_p10']}", p90=f"₹{m['forecast_p90']}")
        return facts, intro, d
    if name == "transport":
        tr = transport_risk(db, f, store=False)
        if not tr.available:
            return [], _t("no_route", loc), d
        src = _src("Risk from rainfall and terrain (FasalAlert transport model)", None, tr.computed_at, "model")
        facts.append(Fact("Route risk, next 72 h", _pct(tr.p72 or 0), src))
        intro = _t("route", loc, route=tr.route_name, p=_pct(tr.p72 or 0))
        if tr.deadline:
            facts.append(Fact("Load by", tr.deadline.isoformat(), src))
            intro += _t("deadline", loc, date=tr.deadline.isoformat())
        return facts, intro, d
    if name == "stage":

        st = engine._stage(db, f)
        if st.stage_label:
            facts.append(Fact("Crop stage", st.stage_label[loc], _src("FasalAlert phenology engine", None, iso(now_utc()), "model")))
            intro = _t("stage", loc, crop=crop, stage=st.stage_label[loc])
        else:
            intro = st.explanation[loc] if st.explanation else None
        return facts, intro, d
    if name in WEATHER_INTENTS:
        facts, intro = _weather_facts(f, d, name, loc)
        return facts, intro, d
    if name == "field_info":
        facts, intro = _field_summary(db, f, d, loc)
        return facts, intro, d
    if name == "profile":
        facts, intro = _profile_summary(db, f, loc)
        return facts, intro, d
    # Irrigation, pests, harvest and general advice get no weather risk injected (it would answer another question).
    return facts, intro, d


WEATHER_INTENTS = {"frost": "frost", "heat": "heatwave", "rain": "heavy_rain", "weather": None, "action": None}
FIELD_LABELS = {
    "source": {"en": "Your field details", "mr": "तुमच्या शेताची माहिती", "hi": "आपके खेत की जानकारी"},
    "name": {"en": "Field", "mr": "शेत", "hi": "खेत"},
    "crop": {"en": "Crop", "mr": "पीक", "hi": "फसल"},
    "place": {"en": "Place", "mr": "ठिकाण", "hi": "स्थान"},
    "sown": {"en": "Sowing date", "mr": "पेरणीची तारीख", "hi": "बुवाई की तारीख"},
    "pruned": {"en": "Fruit pruning date", "mr": "फळछाटणीची तारीख", "hi": "फल छंटाई की तारीख"},
    "variety": {"en": "Variety", "mr": "वाण", "hi": "किस्म"},
    "account": {"en": "Your account", "mr": "तुमचे खाते", "hi": "आपका खाता"},
    "your_name": {"en": "Name", "mr": "नाव", "hi": "नाम"},
    "fields": {"en": "Fields", "mr": "शेते", "hi": "खेत"},
    "area": {"en": "Area", "mr": "क्षेत्र", "hi": "क्षेत्रफल"},
    "stage": {"en": "Crop stage", "mr": "पिकाची अवस्था", "hi": "फसल की अवस्था"},
    "hectare": {"en": "ha", "mr": "हेक्टर", "hi": "हेक्टेयर"},
}


def _place(db: Session, f: Field, loc: str) -> str | None:
    """Village, taluka and district as the farmer chose them, in the reader's language."""
    parts: list[str] = []
    for model, key in ((Village, f.village_id), (Taluka, f.taluka_id), (District, f.district_id)):
        row = db.get(model, key) if key is not None else None
        if row is not None:
            parts.append(getattr(row, f"name_{loc}", None) or row.name_en)
    return ", ".join(parts) or None


def _profile_summary(db: Session, f: Field, loc: str) -> tuple[list[Fact], str]:
    """"What is my name", "where is my farm": the account as the farmer saved it, and every field with its place."""
    user = db.get(User, f.user_id)
    mine = _src(FIELD_LABELS["account"][loc], None, iso(user.updated_at) if user and user.updated_at else None, None)
    fields = db.execute(select(Field).where(Field.user_id == f.user_id).order_by(Field.id)).scalars().all()
    facts: list[Fact] = []
    if user and user.name:
        facts.append(Fact(FIELD_LABELS["your_name"][loc], user.name, mine))
        intro = _t("profile_name", loc, name=user.name)
    else:
        intro = _t("profile_no_name", loc)
    items = []
    facts.append(Fact(FIELD_LABELS["fields"][loc], str(len(fields)), mine))
    for x in fields:
        crop = engine.CROP_NAMES[loc][x.crop]
        place = _place(db, x, loc)
        items.append(f"{x.name or crop} ({crop}{', ' + place if place else ''})")
        # Each field is a fact of its own, so a name with digits ("plot 12") passes the number check.
        facts.append(Fact(x.name or crop, f"{crop}{', ' + place if place else ''}", mine))
    intro += _t("profile_fields", loc, count=len(fields), list="; ".join(items))
    return facts, intro


def _field_summary(db: Session, f: Field, d: dict[str, Any], loc: str) -> tuple[list[Fact], str]:
    """"What is this field", "what crop am I growing here", "help": what FasalAlert knows about the selected field,
    from what the farmer saved, the crop stage and today's weather check. Nothing here is estimated or invented."""
    crop = engine.CROP_NAMES[loc][f.crop]
    mine = _src(FIELD_LABELS["source"][loc], None, iso(f.updated_at) if f.updated_at else None, None)
    name = f.name or crop
    place = _place(db, f, loc)
    facts = [Fact(FIELD_LABELS["name"][loc], name, mine), Fact(FIELD_LABELS["crop"][loc], crop, mine)]
    intro = _t("field_name", loc, name=name, crop=crop)
    if place:
        facts.append(Fact(FIELD_LABELS["place"][loc], place, mine))
        intro += _t("field_place", loc, place=place)
    intro += _t("field_end", loc)
    if f.variety:
        facts.append(Fact(FIELD_LABELS["variety"][loc], f.variety, mine))
        intro += _t("field_variety", loc, variety=f.variety)
    if f.sowing_date:
        sown = f.sowing_date.isoformat()
        # Grapes count the season from fruit pruning, other crops from sowing or planting.
        pruned = f.crop == "grape"
        facts.append(Fact(FIELD_LABELS["pruned" if pruned else "sown"][loc], sown, mine))
        intro += _t("field_pruned" if pruned else "field_sown", loc, date=sown)
    if f.area_sqm:
        area = f"{f.area_sqm / 10_000:.2f}".rstrip("0").rstrip(".") + f" {FIELD_LABELS['hectare'][loc]}"
        facts.append(Fact(FIELD_LABELS["area"][loc], area, mine))
        intro += _t("field_area", loc, area=area)
    if f.sowing_date is None:
        intro += _t("field_no_sowing", loc)
    else:
        st = engine._stage(db, f)
        if st.stage_label:
            facts.append(Fact(FIELD_LABELS["stage"][loc], st.stage_label[loc], _src("FasalAlert phenology engine", None, iso(now_utc()), "model")))
            intro += " " + _t("stage", loc, crop=crop, stage=st.stage_label[loc])
    wx_facts, wx_intro = _weather_facts(f, d, "weather", loc)
    facts += wx_facts
    if wx_intro:
        intro += " " + wx_intro
    intro += _t("field_more", loc)
    return facts, intro
TEMPLATE_CONSTANTS = ["3", "64.5"]


def _weather_facts(f: Field, d: dict[str, Any], name: str, loc: str) -> tuple[list[Fact], str | None]:
    """Facts for the risk the farmer asked about, and only that risk. A missing risk is said to be missing,
    never replaced by another kind (a frost question is never answered with heat)."""
    from app.services.decision import policy

    crop = engine.CROP_NAMES[loc][f.crop]
    if not d:
        return [], _t("wx_unavailable", loc, crop=crop)
    if d.get("abstain_reason") == "data_stale":
        return [], _t("wx_stale", loc)
    if d.get("abstain_reason") == "missing_field_input":
        return [], _t("need_sowing", loc, crop=crop)
    risks = [r for r in d.get("risks", []) if r["kind"] in ("frost", "heatwave", "heavy_rain")]
    checks = d.get("checks") or {}
    want = WEATHER_INTENTS[name]
    if want:
        chosen = [r for r in risks if r["kind"] == want]
        if not chosen:
            return _missing(f, want, checks, loc)
        return _describe(f, max(chosen, key=lambda r: r["probability"]), loc)
    top = max(risks, key=lambda r: (policy.rank(r["level"]), r["probability"]), default=None)
    if top and top["level"] != "none":
        return _describe(f, top, loc)
    rain = checks.get("rain") or {}
    if rain.get("evaluated") or any(r["kind"] == "heavy_rain" for r in risks):
        return [], _t("no_risk", loc, crop=crop)
    return [], _t("no_temp_risk", loc, crop=crop)


def _missing(f: Field, kind: str, checks: dict[str, Any], loc: str) -> tuple[list[Fact], str]:
    crop = engine.CROP_NAMES[loc][f.crop]
    if kind == "heavy_rain":
        rain = checks.get("rain") or {}
        if not rain.get("evaluated"):
            return [], _t("rain_unavailable", loc, crop=crop)
        src = _src("ECMWF ensemble via Open-Meteo (FasalAlert heavy-rain rule)", "https://open-meteo.com", rain.get("forecast_fetched_at"), "forecast")
        p = _pct(rain.get("max_p_heavy") or 0.0)
        facts = [Fact("Heavy-rain chance, next 3 days", p, src)]
        if rain.get("max_rain_mm") is not None:
            facts.append(Fact("Highest daily rain forecast", f"{rain['max_rain_mm']:g} mm", src))
        return facts, _t("rain_none", loc, crop=crop, days=rain.get("days") or 3, p=p)
    status = checks.get("frost" if kind == "frost" else "heat")
    key = "not_scored" if status == "no_threshold" else "kind_unavailable"
    label = engine.KIND_NAMES[loc][kind]
    return [], _t(key, loc, crop=crop, kind=label if key == "not_scored" else label.lower() if loc == "en" else label)


def _describe(f: Field, r: dict[str, Any], loc: str) -> tuple[list[Fact], str]:
    crop = engine.CROP_NAMES[loc][f.crop]
    ev = r.get("evidence", {})
    date = ev.get("event_date", "")
    p = _pct(r["probability"])
    if r["kind"] == "heavy_rain":
        src = _src("ECMWF ensemble via Open-Meteo (FasalAlert heavy-rain rule)", "https://open-meteo.com", ev.get("forecast_fetched_at"), "forecast")
        facts = [Fact("Heavy-rain chance", p, src), Fact("Date", date, src)]
        intro = _t("rain", loc, crop=crop, date=date, p=p)
        if ev.get("forecast_rain_mm") is not None:
            mm = f"{ev['forecast_rain_mm']:g} mm"
            facts.append(Fact("Forecast rain", mm, src))
            intro += _t("rain_mm", loc, mm=mm)
        return facts, intro
    if r.get("tmin_c") is None or r.get("threshold_c") is None:
        return [], _t("kind_unavailable", loc, crop=crop, kind=engine.KIND_NAMES[loc][r["kind"]].lower() if loc == "en" else engine.KIND_NAMES[loc][r["kind"]])
    src = _src("Open-Meteo forecast with FasalAlert frost/heat model", "https://open-meteo.com", ev.get("forecast_fetched_at"), "forecast")
    value, thr = f"{r['tmin_c']} °C", f"{r['threshold_c']:g} °C"
    facts = [Fact("Forecast", value, src), Fact("Threshold", thr, src), Fact("Chance", p, src), Fact("Date", date, src)]
    stage = _stage_label(f.crop, ev.get("stage"), loc) or T["stage_generic"][loc]
    intro = _t("risk_frost" if r["kind"] == "frost" else "risk_heat", loc, crop=crop, value=value, date=date, stage=stage, thr=thr, p=p)
    if ev.get("skill_status") in ("preliminary", "not_demonstrated", "not_evaluated"):
        intro += _t("skill_caveat", loc)
    return facts, intro


def _names_own_field(db: Session, user: User, text: str) -> bool:
    """The question names one of the farmer's own fields or varieties ("my G spot field", "Manik Chaman")."""
    low = text.lower()
    for name, variety in db.execute(select(Field.name, Field.variety).where(Field.user_id == user.id)).all():
        for v in (name, variety):
            if v and len(v.strip()) >= 2 and v.strip().lower() in low:
                return True
    return False


def ask(db: Session, user: User, text: str | None, audio_b64: str | None, field_id: int | None, locale: str,
        history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    used = asks_used_today(db, user)
    if used >= ASK_DAILY_LIMIT:
        raise ApiError("rate_limited", "Daily question limit reached", {"retry_after": 3600, "limit": ASK_DAILY_LIMIT})
    remaining = ASK_DAILY_LIMIT - used - 1
    base: dict[str, Any] = {"answer": "", "answer_audio_url": None, "cards": [], "abstain": False, "sources": [],
                            "asr_confidence": None, "dw_wer": None, "transcript": None, "low_confidence_terms": [],
                            "abstain_reason": None, "kvk": None, "intent": None, "asks_remaining": remaining,
                            "stt_available": speech.stt_available()}
    if audio_b64:
        try:
            audio = base64.b64decode(audio_b64, validate=True)
        except ValueError as e:
            raise ApiError("validation_error", "Audio could not be read", {"field": "audio_b64"}) from e
        if len(audio) > 3_000_000:
            raise ApiError("validation_error", "Recording too long", {"field": "audio_b64"})
        stt = speech.transcribe(audio, locale)
        if not stt.available:
            audit(db, user.id, "ask", "assistant", None, intent="stt_unavailable")
            return {**base, "intent": "stt_unavailable"}
        base["asr_confidence"] = stt.confidence
        base["transcript"] = stt.text or ""
        if not stt.text:
            return {**base, "intent": "no_speech"}  # PRD §7.5 silent recording: not counted as a question
        low = set(w.lower() for w in stt.low_confidence_words)
        base["low_confidence_terms"] = [{"text": w, "domain_term": w.lower() in alias_index()} for w in stt.low_confidence_words]
        text = stt.text
        if (stt.confidence is not None and stt.confidence < UNSURE) or low:
            base["intent"] = "confirm_transcript"  # client shows "did I hear this right?" and lets the farmer edit
    if not text or not text.strip():
        raise ApiError("validation_error", "Ask a question", {"field": "text"})
    intent = intents.resolve(text)
    if not intent.agricultural and _names_own_field(db, user, text):
        intent = intents.Intent("field_info", intent.crops, intent.signals | {"field_info"}, True)
    outside = {**base, "abstain": True, "abstain_reason": "outside_domain", "answer": _t("outside", locale), "intent": "outside_domain"}
    # Keywords cannot judge every question (typos, follow-ups such as "I am asking about my field"). With the model
    # configured, a question they cannot place goes to it with the farmer's context, and the model says when it is
    # off-topic. Without the model, keywords decide (ASK-13).
    unplaced = not intent.agricultural
    if unplaced and not groq_enabled():
        audit(db, user.id, "ask", "assistant", None, intent="outside_domain")
        return outside
    if unplaced:
        intent = intents.Intent("general", intent.crops, intent.signals, True)
    base["intent"] = base["intent"] or intent.name
    audit(db, user.id, "ask", "assistant", None, intent=intent.name)
    f = _pick_field(db, user, field_id, intent)
    if f is None:
        return outside if unplaced else {**base, "answer": _t("no_field", locale)}
    kvk = kvk_for(db, f) or fallback_contact()
    # The crop the farmer names wins over the selected field: never answer a cotton question with mango advice.
    crop = intent.crop or f.crop
    if crop == f.crop:
        facts, intro, d = _facts_for(db, f, intent, locale)
    else:
        facts, intro, d = [], None, {}
    stage = None
    for r in (d or {}).get("risks", []):
        stage = r.get("evidence", {}).get("stage") or stage
    need = intent.name in NEEDS_ADVICE
    # Always retrieve verified advice when Groq is on so the model can ground farm guidance.
    # Bound RAG so a cold embedding-model download cannot hang Ask forever.
    # Advisory passages only when advice is asked for: they are most of the model's tokens (8000 a minute on Groq's
    # free tier) and a question about the field itself or the account needs none.
    want_rag = need or (groq_enabled() and intent.name in ("general", "advisory"))
    hits: list[rag.Hit] = []
    if want_rag:
        def _retrieve() -> list[rag.Hit]:
            found = rag.above_threshold(
                rag.search(db, text, crop=crop, stage=stage, topic=TOPIC_FOR.get(intent.name), k=5)
            )
            return [h for h in found if h.crop in (crop, None)]

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            hits = pool.submit(_retrieve).result(timeout=12)
        except FuturesTimeout:
            log.warning("ask rag_retrieve_timeout; continuing with field facts only")
            hits = []
        except Exception:  # noqa: BLE001 - never block Ask on embed/model download failures
            log.exception("ask rag_retrieve_failed; continuing with field facts only")
            hits = []
        finally:
            # A cold HF download can hang forever; do not join that thread on the Ask path.
            pool.shutdown(wait=False, cancel_futures=True)
    use_llm = groq_enabled() and intent.agricultural
    llm_answer: str | None = None
    if use_llm:
        ctx = build_context(
            db=db, user=user, question=text, locale=locale, intent=intent, field=f,
            decision=d, facts=facts, hits=hits, intro=intro, kvk=kvk,
        )
        allowed = allowed_number_tokens(facts, intro, hits, TEMPLATE_CONSTANTS)
        llm_answer = draft_answer(ctx, locale, text, allowed, history)
    if llm_answer == OUTSIDE or (unplaced and not llm_answer):
        return outside
    comp = compose(text, locale, facts, hits, intro=intro, require_advice=need and not llm_answer,
                   template_constants=TEMPLATE_CONSTANTS, crop=crop)
    out = {**base, "cards": comp.cards, "sources": comp.sources, "kvk": kvk}
    if llm_answer:
        log.info("ask answer_source=groq intent=%s", intent.name)
        # Merge RAG sources into the response even when the spoken answer came from Groq.
        for h in hits[:3]:
            src = {"label": f"{h.institution}: {h.title}" + (f" ({h.year})" if h.year else ""),
                   "url": h.source_url, "fetched_at": None, "kind": "advisory"}
            if src not in out["sources"]:
                out["sources"].append(src)
        out["answer"] = llm_answer
        out["answer_source"] = "groq"
        out["abstain"] = False
        out["abstain_reason"] = None
    elif comp.abstain:
        out.update({"abstain": True, "abstain_reason": comp.abstain_reason,
                    "answer": ((intro + " ") if intro and comp.cards else "") + _t("abstain", locale, kvk=kvk["name"])})
    else:
        out["answer"] = comp.answer
        out["answer_source"] = "compose"
    if out["answer"]:
        tts = speech.synthesize(out["answer"], locale)
        if tts.available:
            out["answer_audio_url"] = f"/api/v1/ask/audio/{tts.audio_id}"
    return out
