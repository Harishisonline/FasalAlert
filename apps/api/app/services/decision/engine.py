"""Decision engine (PRD §3, §8.1 L3, §11.1, §11.2): one decision per field per day.

Chain: phenology -> crop-stage thresholds (with farmer calibration) -> forecast and ensemble ->
frost/heat classifier, heavy-rain ensemble rule, transport susceptibility -> market summary ->
verified advisory retrieval -> one decision, or an abstention.

Rules that keep it honest:
  * confidence is the probability of the primary risk only; probabilities are never multiplied together;
  * an actionable risk without a verified advisory becomes an abstention (no_retrieval_above_threshold);
  * stale or missing forecasts abstain with data_stale; a missing sowing date abstains with missing_field_input;
  * every number carries its source; the full inputs and model versions are stored for reproducibility.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.timeutil import IST, iso, now_utc, today_ist
from app.models.tables import DecisionRow, Field, RiskRow, User
from app.services.decision import policy
from app.services.decision.context import (
    Thresholds,
    calibration,
    fallback_contact,
    kvk_for,
    market_summary,
    thresholds_for,
    transport_risk,
)
from app.services.foundry.climate import recent_with_forecast_past
from app.services.foundry.http import UpstreamError
from app.services.foundry.openmeteo import ForecastBundle, bundle_to_json, get_forecast
from app.services.models import phenology
from app.services.models import price as price_model
from app.services.models import rain as rain_rule
from app.services.models import transport as tm
from app.services.models.frost_interface import FrostFeatures, FrostPrediction
from app.services.models.frost_skill import skill_for
from app.services.rag import retrieve as rag
from app.services.rag.compose import best_sentences

log = logging.getLogger("fasalalert.decision")

CROP_NAMES = {
    "en": {"mango": "mango", "pomegranate": "pomegranate", "grape": "grape", "soybean": "soybean", "cotton": "cotton", "sugarcane": "sugarcane"},
    "mr": {"mango": "आंबा", "pomegranate": "डाळिंब", "grape": "द्राक्ष", "soybean": "सोयाबीन", "cotton": "कापूस", "sugarcane": "ऊस"},
    "hi": {"mango": "आम", "pomegranate": "अनार", "grape": "अंगूर", "soybean": "सोयाबीन", "cotton": "कपास", "sugarcane": "गन्ना"},
}
KIND_NAMES = {
    "en": {"frost": "Frost", "heatwave": "Heat", "heavy_rain": "Heavy rain", "transport": "Road"},
    "mr": {"frost": "दंव", "heatwave": "उष्णता", "heavy_rain": "मुसळधार पाऊस", "transport": "रस्ता"},
    "hi": {"frost": "पाला", "heatwave": "गर्मी", "heavy_rain": "भारी बारिश", "transport": "रास्ता"},
}
LEVEL_NAMES = {
    "en": {"none": "NONE", "low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"},
    "mr": {"none": "नाही", "low": "कमी", "medium": "मध्यम", "high": "जास्त", "critical": "अतिगंभीर"},
    "hi": {"none": "नहीं", "low": "कम", "medium": "मध्यम", "high": "ज़्यादा", "critical": "अति गंभीर"},
}


def _predict(features: FrostFeatures) -> FrostPrediction:
    from app.services.models.frost import predict

    return predict(features)


def _hm(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%H:%M")


def _forecast(db: Session, f: Field) -> tuple[ForecastBundle | None, str | None]:
    try:
        b = get_forecast(db, f.lat, f.lon, field_id=f.id)
    except UpstreamError as e:
        log.warning("forecast unavailable for field %s: %s", f.id, e)
        return None, "upstream"
    if now_utc() - b.fetched_at > policy.FORECAST_STALE_AFTER:
        return b, "stale"
    return b, None


def _stage(db: Session, f: Field) -> phenology.StageResult:
    info = phenology.crop_info(f.crop)
    method = info["phenology"]["method"]
    if method == "calendar":
        return phenology.compute_stage(f.crop, f.sowing_date)
    if f.sowing_date is None:
        return phenology.unknown_stage(f.crop)
    daily = None
    if method == "gdd":
        try:
            hist = recent_with_forecast_past(db, f.lat, f.lon, f.sowing_date)
            daily = [(h.day, h.tmin_c, h.tmax_c) for h in hist]
        except UpstreamError:
            daily = None
    return phenology.compute_stage(f.crop, f.sowing_date, daily)


def _temp_risks(f: Field, b: ForecastBundle, st: phenology.StageResult, th: Thresholds, sens: str) -> list[dict[str, Any]]:
    risks = []
    for kind, thr in (("frost", th.frost_c), ("heat", th.heat_c)):
        if thr is None:
            continue
        best: tuple[FrostPrediction, Any, int] | None = None
        for day in b.days[:3]:
            # the classifier was trained on JMA forecasts; best_match is the fallback (noted in evidence)
            jma = day.tmin_jma_c if kind == "frost" else day.tmax_jma_c
            fc = jma if jma is not None else (day.tmin_c if kind == "frost" else day.tmax_c)
            at = (day.tmin_at if kind == "frost" else day.tmax_at) or datetime.combine(day.valid_date, datetime.min.time(), tzinfo=IST) + timedelta(hours=6 if kind == "frost" else 14)
            if fc is None or at <= b.fetched_at:
                continue  # an event hour already past (today's pre-dawn minimum after sunrise) is not a forecast
            lead = int((at - b.fetched_at).total_seconds() // 3600)
            past = b.past_days[-3:]
            lags = tuple(reversed([(p.tmin_c if kind == "frost" else p.tmax_c) for p in past])) + (None, None, None)
            pred = _predict(FrostFeatures(
                kind=kind, lat=f.lat, lon=f.lon, valid_date=day.valid_date, lead_hours=lead, threshold_c=float(thr),
                forecast_c=float(fc), ensemble_spread_c=day.tmin_spread_c if kind == "frost" else day.tmax_spread_c,
                forecast_rain_mm=day.rain_mm, observed_lags_c=lags[:3], elevation_m=b.elevation_m,
                antecedent_wetness=sum((p.rain_mm or 0) for p in b.past_days[-7:]),
            ))
            if jma is None:
                pred = replace(pred, notes=[*pred.notes, "JMA forecast unavailable: best_match passed, which scored lower in the held-out test"])
            if best is None or pred.probability > best[0].probability:
                best = (pred, (day, at), lead, "jma_seamless" if jma is not None else "best_match")
        if best is None:
            continue
        pred, (day, at), lead, fmodel = best
        skill = skill_for(kind, float(thr))
        k = "frost" if kind == "frost" else "heatwave"
        risks.append({
            "kind": k, "level": policy.level_for(pred.probability, lead, sens), "probability": round(pred.probability, 3),
            "tmin_c": round(pred.point_c, 1), "band_low_c": pred.band_low_c, "band_high_c": pred.band_high_c,
            "threshold_c": float(thr), "window_start": iso(at - timedelta(hours=1)), "window_end": iso(at + timedelta(hours=1)),
            "lead_hours": lead, "model_version": pred.model_version,
            "evidence": {"method": pred.method, "calibrated": pred.calibrated, "forecast_source": "open-meteo",
                         "forecast_model": fmodel, "skill_status": skill["status"], "skill": skill, "forecast_fetched_at": iso(b.fetched_at), "ensemble_model": b.ensemble_model,
                         "ensemble_members": day.members, "field_elevation_m": b.elevation_m, "gdd_cum": st.gdd_cum,
                         "stage": st.stage, "threshold_source_id": th.source_id, "threshold_overridden": th.overridden,
                         "event_date": day.valid_date.isoformat(), "event_at": iso(at), "notes": pred.notes,
                         "value_kind": "tmin" if kind == "frost" else "tmax"},
            "_event_at": at,
        })
    return risks


def _rain_risk(b: ForecastBundle, sens: str) -> dict[str, Any] | None:
    best = None
    for day in b.days[:rain_rule.HORIZON_DAYS]:
        if day.rain_p_heavy is None:
            continue
        if best is None or day.rain_p_heavy > best.rain_p_heavy:
            best = day
    if best is None or (best.rain_p_heavy or 0) < rain_rule.MIN_REPORTED_P:
        return None
    at = datetime.combine(best.valid_date, datetime.min.time(), tzinfo=IST) + timedelta(hours=12)
    lead = max(0, int((at - b.fetched_at).total_seconds() // 3600))
    return {"kind": "heavy_rain", "level": policy.level_for(best.rain_p_heavy, lead, sens), "probability": best.rain_p_heavy,
            "threshold_c": None, "window_start": iso(at - timedelta(hours=12)), "window_end": iso(at + timedelta(hours=12)),
            "lead_hours": lead, "model_version": rain_rule.VERSION,
            "evidence": {"method": "rule", "rule": rain_rule.RULE,
                         "ensemble_members": best.members, "forecast_rain_mm": best.rain_mm, "forecast_source": "open-meteo",
                         "forecast_fetched_at": iso(b.fetched_at), "event_date": best.valid_date.isoformat()},
            "_event_at": at}


def _checks(b: ForecastBundle, th: Any, risks: list[dict[str, Any]]) -> dict[str, Any]:
    """Which risk checks ran, so an answer can say "not scored" or "not available" instead of "no risk"."""
    kinds = {r["kind"] for r in risks}
    def temp(kind: str, thr: float | None) -> str:
        if thr is None:
            return "no_threshold"
        return "evaluated" if kind in kinds else "no_forecast"
    days = b.days[:rain_rule.HORIZON_DAYS]
    p = [d.rain_p_heavy for d in days if d.rain_p_heavy is not None]
    mm = [d.rain_mm for d in days if d.rain_mm is not None]
    return {"frost": temp("frost", th.frost_c), "heat": temp("heatwave", th.heat_c),
            "rain": {"evaluated": bool(p), "max_p_heavy": round(max(p), 3) if p else None,
                     "max_rain_mm": round(max(mm), 1) if mm else None, "days": len(days),
                     "ensemble_model": b.ensemble_model, "forecast_fetched_at": iso(b.fetched_at)}}


def _advisory(db: Session, crop: str, stage: str | None, kind: str) -> rag.Hit | None:
    q, topic = policy.ADVISORY_QUERY.get(kind, ("", None))
    hits = rag.above_threshold(rag.search(db, f"{crop} {q}", crop=crop, stage=stage, topic=topic, k=5))
    return next((h for h in hits if h.crop in (crop, None)), None)


def _i18n_headline(kind: str, level: str, r: dict[str, Any]) -> dict[str, str]:
    out = {}
    for loc in ("en", "mr", "hi"):
        k, lv = KIND_NAMES[loc][kind], LEVEL_NAMES[loc][level]
        if kind in ("frost", "heatwave") and r.get("tmin_c") is not None and r.get("_event_at"):
            out[loc] = {"en": f"{k} risk {lv}: {r['tmin_c']} °C forecast at {_hm(r['_event_at'])}",
                        "mr": f"{k} धोका {lv}: {_hm(r['_event_at'])} वाजता {r['tmin_c']} °C अंदाज",
                        "hi": f"{k} खतरा {lv}: {_hm(r['_event_at'])} बजे {r['tmin_c']} °C पूर्वानुमान"}[loc]
        else:
            out[loc] = {"en": f"{k} risk {lv}", "mr": f"{k} धोका {lv}", "hi": f"{k} खतरा {lv}"}[loc]
    return out


def _no_risk_text(crop: str) -> tuple[dict[str, str], dict[str, str]]:
    head = {"en": "No weather risk today", "mr": "आज हवामानाचा धोका नाही", "hi": "आज मौसम का कोई खतरा नहीं"}
    act = {"en": f"No weather risk for your {CROP_NAMES['en'][crop]} today.",
           "mr": f"आज तुमच्या {CROP_NAMES['mr'][crop]} पिकाला हवामानाचा धोका नाही.",
           "hi": f"आज आपकी {CROP_NAMES['hi'][crop]} फसल को मौसम का कोई खतरा नहीं है."}
    return head, act


def _abstain(f: Field, reason: str, kvk: dict[str, str] | None, risks: list[dict[str, Any]], last_update: datetime | None = None) -> dict[str, Any]:
    texts = {
        "missing_field_input": ({"en": "Recommendation unavailable", "mr": "सल्ला उपलब्ध नाही", "hi": "सलाह उपलब्ध नहीं"},
                                {"en": "Add your sowing date so the crop stage can be worked out.",
                                 "mr": "पिकाची अवस्था ठरवण्यासाठी पेरणीची तारीख भरा.",
                                 "hi": "फसल की अवस्था तय करने के लिए बुवाई की तारीख भरें."}),
        "data_stale": ({"en": "Recommendation unavailable", "mr": "सल्ला उपलब्ध नाही", "hi": "सलाह उपलब्ध नहीं"},
                       {"en": "Weather data is out of date, so no recommendation is given.",
                        "mr": "हवामानाची माहिती जुनी आहे, म्हणून सल्ला दिला जात नाही.",
                        "hi": "मौसम की जानकारी पुरानी है, इसलिए सलाह नहीं दी जा रही."}),
        "model_confidence_below_threshold": ({"en": "Too uncertain to advise today", "mr": "आज सल्ला देण्याइतकी खात्री नाही", "hi": "आज सलाह देने लायक भरोसा नहीं"},
                                             {"en": "The forecast is too uncertain for a clear recommendation. Call your KVK for advice.",
                                              "mr": "अंदाज खूप अनिश्चित आहे. सल्ल्यासाठी KVK ला फोन करा.",
                                              "hi": "पूर्वानुमान बहुत अनिश्चित है. सलाह के लिए KVK को फ़ोन करें."}),
        "no_retrieval_above_threshold": ({"en": "Recommendation unavailable", "mr": "सल्ला उपलब्ध नाही", "hi": "सलाह उपलब्ध नहीं"},
                                         {"en": "I do not have a verified advisory for this situation. Call your district Krishi Vigyan Kendra for advice.",
                                          "mr": "या परिस्थितीसाठी माझ्याकडे खात्रीशीर सल्ला नाही. सल्ल्यासाठी जिल्हा कृषी विज्ञान केंद्राला फोन करा.",
                                          "hi": "इस स्थिति के लिए मेरे पास प्रमाणित सलाह नहीं है. सलाह के लिए ज़िला कृषि विज्ञान केंद्र को फ़ोन करें."}),
    }
    head, act = texts[reason]
    return {"field_id": f.id, "decision_date": today_ist().isoformat(), "headline": head["en"], "action_text": act["en"],
            "confidence": 0.0, "abstain_reason": reason, "risks": [_public_risk(r) for r in risks],
            "kvk": kvk or fallback_contact(), "last_update": iso(last_update),
            "_i18n": {"headline": head, "action_text": act}}


def _public_risk(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def compute(db: Session, f: Field, store: bool = True) -> dict[str, Any]:
    owner = db.get(User, f.user_id)
    cal = calibration(db, f)
    kvk = kvk_for(db, f)
    st = _stage(db, f)
    th = thresholds_for(f.crop, st.stage, cal)
    inputs: dict[str, Any] = {"field": {"id": f.id, "crop": f.crop, "variety": f.variety, "lat": f.lat, "lon": f.lon,
                                         "sowing_date": f.sowing_date.isoformat() if f.sowing_date else None},
                              "calibration": {"sensitivity": cal.sensitivity, "frost_threshold_c": cal.frost_threshold_c,
                                              "heat_threshold_c": cal.heat_threshold_c, "harvest_lead_hours": cal.harvest_lead_hours},
                              "stage": st.to_api(), "thresholds": asdict(th), "policy": policy.POLICY_VERSION}
    versions = {"phenology": phenology.VERSION, "policy": policy.POLICY_VERSION}

    if st.stage is None and phenology.crop_info(f.crop)["phenology"]["method"] != "calendar":
        result = _abstain(f, "missing_field_input", kvk, [])
        return _finish(db, f, result, inputs, versions, store, owner)

    bundle, problem = _forecast(db, f)
    if bundle is None or problem == "stale":
        result = _abstain(f, "data_stale", kvk, [], bundle.fetched_at if bundle else None)
        return _finish(db, f, result, inputs, versions, store, owner)
    inputs["forecast"] = bundle_to_json(bundle)

    risks = _temp_risks(f, bundle, st, th, cal.sensitivity)
    rain = _rain_risk(bundle, cal.sensitivity)
    if rain:
        risks.append(rain)
    tr = transport_risk(db, f)
    if tr.available and tr.p72 is not None:
        risks.append({"kind": "transport", "level": tm.level(tr.p72), "probability": tr.p72, "threshold_c": None,
                      "lead_hours": 72, "model_version": tm.VERSION,
                      "evidence": {"method": "rule", "calibrated": False, "route_name": tr.route_name, "note": tm.NOTE,
                                   "rain_accum_mm_72h": tr.rain72, "source": "open-meteo + osm-roads + srtm"}})
    for r in risks:
        versions[{"frost": "frost", "heatwave": "frost", "heavy_rain": "rain", "transport": "transport"}[r["kind"]]] = r["model_version"]
    inputs["transport"] = asdict(tr)

    market = market_summary(db, f, tr.p72 if tr.available else None)
    if market:
        versions["price"] = price_model.VERSION

    primary = max(risks, key=lambda r: (policy.rank(r["level"]), r["probability"]), default=None)
    sources = [{"label": "Open-Meteo forecast (CC BY 4.0)", "url": "https://open-meteo.com", "fetched_at": iso(bundle.fetched_at), "kind": "forecast"}]
    if market:
        sources.append({"label": f"AGMARKNET {market['market']} {market['commodity']}", "url": "https://agmarknet.gov.in",
                        "fetched_at": market["price_date"], "kind": "market", "synthetic": market["source"] == "synthetic_seed"})

    if primary and primary["kind"] in ("frost", "heatwave") and policy.too_uncertain(primary.get("band_low_c"), primary.get("band_high_c"), primary["probability"]):
        return _finish(db, f, {**_abstain(f, "model_confidence_below_threshold", kvk, risks), "checks": _checks(bundle, th, risks)}, inputs, versions, store, owner)

    advisory = None
    if primary and primary["level"] in policy.ACTIONABLE:
        hit = _advisory(db, f.crop, st.stage, primary["kind"])
        if hit is None:
            return _finish(db, f, {**_abstain(f, "no_retrieval_above_threshold", kvk, risks), "checks": _checks(bundle, th, risks)}, inputs, versions, store, owner)
        quote = " ".join(best_sentences(hit, policy.ADVISORY_QUERY[primary["kind"]][0], crop=f.crop))
        if not quote:
            return _finish(db, f, {**_abstain(f, "no_retrieval_above_threshold", kvk, risks), "checks": _checks(bundle, th, risks)}, inputs, versions, store, owner)
        advisory = {"text": quote, "source": f"{hit.institution}, {hit.title}", "source_url": hit.source_url,
                    "institution": hit.institution, "year": hit.year, "verified": True, "similarity": round(hit.similarity, 3)}
        sources.append({"label": f"{hit.institution}: {hit.title}", "url": hit.source_url, "fetched_at": iso(now_utc()), "kind": "advisory"})
        when = policy.act_by(primary["kind"], primary["_event_at"]) if primary.get("_event_at") else None
        if primary["kind"] == "transport" and tr.deadline:
            when = datetime.combine(tr.deadline, datetime.min.time(), tzinfo=IST) + timedelta(hours=18)
        head = _i18n_headline(primary["kind"], primary["level"], primary)
        tstr = _hm(when) if when else None
        prefix = {"en": f"Act by {tstr}." if tstr else "", "mr": f"{tstr} पूर्वी उपाय करा." if tstr else "",
                  "hi": f"{tstr} से पहले उपाय करें." if tstr else ""}
        act = {loc: (prefix[loc] + " " + quote).strip() for loc in ("en", "mr", "hi")}
        confidence = primary["probability"]
        action_by = iso(when)
    else:
        head, act = _no_risk_text(f.crop)
        confidence = round(1 - max((r["probability"] for r in risks), default=0.0), 3)
        action_by = None

    recommendation = _recommendation(market, tr)
    result = {
        "field_id": f.id, "decision_date": today_ist().isoformat(), "headline": head["en"], "action_text": act["en"],
        "action_by": action_by, "confidence": round(confidence, 3), "abstain_reason": None,
        "risks": [_public_risk(r) for r in risks],
        "market": {k: v for k, v in market.items() if not k.startswith("_")} if market else None,
        "transport": {"route_name": tr.route_name, "p_disruption_72h": tr.p72, "rain_accum_mm_72h": tr.rain72,
                      "harvest_deadline": tr.deadline.isoformat() if tr.deadline else None, "model_version": tm.VERSION,
                      "note": tm.NOTE, "source": "open-meteo + osm-roads + srtm"} if tr.available else None,
        "recommendation": recommendation, "advisory": advisory, "sources": sources, "model_versions": versions,
        "limitations": _limitations(risks, tr, market),
        "checks": _checks(bundle, th, risks),
        "_i18n": {"headline": head, "action_text": act, "net_reason": recommendation.get("_i18n") if recommendation else None},
    }
    if recommendation:
        recommendation.pop("_i18n", None)
    return _finish(db, f, result, inputs, versions, store, owner)


def _recommendation(market: dict[str, Any] | None, tr: Any) -> dict[str, Any] | None:
    if not market:
        return None
    pts = market.get("_forecast_points") or []
    deadline = tr.deadline if tr.available else None
    hold_until, reason_en = None, "Price forecast unavailable; showing the current price only."
    reason = {"en": reason_en, "mr": "भावाचा अंदाज उपलब्ध नाही; फक्त सध्याचा भाव दाखवला आहे.",
              "hi": "भाव का पूर्वानुमान उपलब्ध नहीं; केवल मौजूदा भाव दिखाया गया है."}
    if pts:
        today_price = market["modal_rs_qtl"]
        best = max(pts, key=lambda p: p["p50"])
        gain = (best["p50"] / today_price - 1) * 100
        best_day = date.fromisoformat(best["date"])
        if gain >= 3:
            hold_until = best_day
            if deadline and deadline < best_day:
                hold_until = deadline
            reason = {"en": f"Median forecast {best['p50']} by {best['date']}, against {round(today_price)} today.",
                      "mr": f"{best['date']} पर्यंत अंदाजे मध्य भाव {best['p50']}, आज {round(today_price)}.",
                      "hi": f"{best['date']} तक अनुमानित मध्य भाव {best['p50']}, आज {round(today_price)}."}
        else:
            reason = {"en": f"No meaningful rise expected: median forecast {best['p50']} against {round(today_price)} today.",
                      "mr": f"भाव फारसा वाढण्याची शक्यता नाही: अंदाजे मध्य भाव {best['p50']}, आज {round(today_price)}.",
                      "hi": f"भाव में खास बढ़त की संभावना नहीं: अनुमानित मध्य भाव {best['p50']}, आज {round(today_price)}."}
    if not tr.available:
        for k, v in {"en": " Price advice only, route unknown.", "mr": " फक्त भावाचा सल्ला, मार्ग माहीत नाही.",
                     "hi": " केवल भाव की सलाह, रास्ता ज्ञात नहीं."}.items():
            reason[k] += v
    return {"harvest_on": deadline.isoformat() if deadline else None, "sell_at": market["market"],
            "hold_until": hold_until.isoformat() if hold_until else None, "net_reason": reason["en"], "_i18n": reason}


def _limitations(risks: list[dict[str, Any]], tr: Any, market: dict[str, Any] | None) -> list[str]:
    out = []
    if any(r["kind"] in ("frost", "heatwave") for r in risks):
        out.append("Temperature risk comes from gridded forecasts about 25 km to 100 km across; it cannot see a frost pocket inside your farm.")
    if tr.available:
        out.append(tm.NOTE)
    if market and market.get("source") == "synthetic_seed":
        out.append("Market prices shown are synthetic sample data, not real AGMARKNET prices.")
    if market and not market.get("forecast_available"):
        out.append("No price forecast is served for this market because the model has not beaten a simple seasonal forecast.")
    return out


def _finish(db: Session, f: Field, result: dict[str, Any], inputs: dict[str, Any], versions: dict[str, str], store: bool, owner: User | None) -> dict[str, Any]:
    if store:
        d = today_ist()
        db.execute(delete(RiskRow).where(RiskRow.field_id == f.id, RiskRow.computed_at >= datetime.combine(d, datetime.min.time(), tzinfo=IST)))
        risk_ids = []
        for r in result.get("risks", []):
            row = RiskRow(field_id=f.id, kind=r["kind"], level=r["level"], probability=r["probability"],
                          tmin_band_low=r.get("band_low_c"), tmin_band_high=r.get("band_high_c"), threshold_c=r.get("threshold_c"),
                          window_start=_dt(r.get("window_start")), window_end=_dt(r.get("window_end")), lead_hours=r.get("lead_hours"),
                          evidence=r.get("evidence", {}), model_version=r["model_version"], method=r.get("evidence", {}).get("method", "model"))
            db.add(row)
            db.flush()
            risk_ids.append(row.id)
        stmt = insert(DecisionRow).values(
            field_id=f.id, decision_date=d, headline=result["headline"], action_text=result["action_text"],
            action_by=_dt(result.get("action_by")), confidence=result.get("confidence"), abstain_reason=result.get("abstain_reason"),
            risk_ids=risk_ids, price_summary=result.get("market") or {}, transport_summary=result.get("transport") or {},
            sources=result.get("sources", []), model_versions=versions, inputs=_jsonable(inputs),
            policy_version=policy.POLICY_VERSION, payload=_jsonable(result))
        stmt = stmt.on_conflict_do_update(index_elements=["field_id", "decision_date"], set_={
            c: stmt.excluded[c] for c in ("headline", "action_text", "action_by", "confidence", "abstain_reason", "risk_ids",
                                          "price_summary", "transport_summary", "sources", "model_versions", "inputs",
                                          "policy_version", "payload")})
        db.execute(stmt)
        db.flush()
    return result


def _dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items() if not (isinstance(k, str) and k == "_event_at")}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, date | datetime):
        return o.isoformat()
    return o


def localize(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    """Render a stored decision in the requested locale; numbers and quotes are unchanged."""
    out = {k: v for k, v in payload.items() if k != "_i18n"}
    i18n = payload.get("_i18n") or {}
    for key in ("headline", "action_text"):
        if i18n.get(key, {}).get(locale):
            out[key] = i18n[key][locale]
    nr = i18n.get("net_reason")
    if nr and out.get("recommendation") and nr.get(locale):
        out["recommendation"] = {**out["recommendation"], "net_reason": nr[locale]}
    return out


def latest(db: Session, field_id: int) -> DecisionRow | None:
    return db.execute(select(DecisionRow).where(DecisionRow.field_id == field_id).order_by(DecisionRow.decision_date.desc())).scalars().first()
