"""DW-WER (AC 13, 14), number grounding (AC 11), intents (AC 16)."""
from app.services.rag.compose import Fact, compose, validate_numbers
from app.services.rag.retrieve import Hit
from app.services.voice import intents
from app.services.voice.dwwer import category, score


def test_chemical_mishearing_weighs_20x():
    ref = "आंब्यावर क्लोरपायरीफॉस फवारा मग पाणी द्या"
    chem = score(ref, "आंब्यावर क्लोरोफॉर्म फवारा मग पाणी द्या")
    filler = score(ref, "आंब्यावर क्लोरपायरीफॉस फवारा पाणी द्या")
    assert chem.errors == filler.errors == 1          # WER counts both as one error
    assert chem.wer == filler.wer
    assert chem.weighted_errors == 20 and filler.weighted_errors == 1   # DW-WER weighs the chemical 20x
    assert chem.dw_wer == __import__("pytest").approx(20 * filler.dw_wer)


def test_categories_handle_marathi_inflection_and_multiword():
    assert category("आंब्यावर") == "crop"
    assert category("द्राक्षाला") == "crop"
    assert category("copper_oxychloride") == "chemical"
    assert category("3.5") == "quantity"
    assert category("नाशिकमध्ये") == "place"


def test_perfect_transcript_scores_zero():
    s = score("Irrigate the mango basin tonight", "irrigate the mango basin tonight")
    assert s.wer == 0 and s.dw_wer == 0


def test_validator_rejects_invented_number():
    assert validate_numbers("Tmin 3.2 °C", ["3.2 °C"])
    assert not validate_numbers("Tmin 3.2 °C, spray 40 ml", ["3.2 °C"])


def _hit(content, **kw):
    base = dict(id=1, doc_id="d1", institution="ICAR-CISH", title="Frost protection", year=2019, source_url="https://example.org/a.pdf",
                license="x", lang="en", crop="mango", stage=None, topics=[], content=content, page=1, similarity=0.8, score=0.05)
    base.update(kw)
    return Hit(**base)


def test_compose_quotes_with_citation_and_abstains_without_hits():
    fact = Fact("Forecast", "3.2 °C", {"label": "Open-Meteo", "url": "https://open-meteo.com", "fetched_at": None})
    hit = _hit("Light irrigation before a frost night keeps the soil warm and protects mango flowers from frost injury.")
    c = compose("frost on mango tonight", "en", [fact], [hit], intro="Forecast 3.2 °C.")
    assert not c.abstain and "ICAR-CISH" in c.answer and "“" in c.answer
    assert any(s.get("url") == "https://example.org/a.pdf" for s in c.sources)
    none = compose("frost on mango tonight", "en", [fact], [], intro="Forecast 3.2 °C.")
    assert none.abstain and none.abstain_reason == "no_retrieval_above_threshold"


def test_compose_abstains_if_template_injects_unsupported_number():
    hit = _hit("Irrigate the basin lightly before a frost night to protect the flowers of mango trees.")
    c = compose("frost", "en", [], [hit], intro="Spray 25 ml per litre.")   # 25 is not in any context
    assert c.abstain


def test_intents():
    assert intents.resolve("आजचा भाव किती?").name == "price"
    assert intents.resolve("मार्ग खुला आहे का?").name == "transport"
    assert intents.resolve("आंब्यावर दंव पडेल का?").name == "frost"
    outside = intents.resolve("Who won the cricket match yesterday?")
    assert not outside.agricultural and outside.name == "outside_domain"


def test_dose_never_quoted_from_another_crop_or_general_source():
    from app.services.rag.compose import best_sentences

    text = ("Spray copper oxychloride 0.3 percent at 20 day intervals to control bacterial blight disease. "
            "Remove and destroy infected twigs to reduce bacterial blight disease spread in the orchard.")
    mango_doc = _hit(text, crop="mango")
    general_doc = _hit(text, crop=None)
    q = "How to control bacterial blight disease?"
    assert any("0.3" in s for s in best_sentences(mango_doc, q, crop="mango"))
    assert all("0.3" not in s for s in best_sentences(mango_doc, q, crop="pomegranate"))
    assert all("0.3" not in s for s in best_sentences(general_doc, q, crop="pomegranate"))
    assert best_sentences(general_doc, q, crop="pomegranate")          # non-dose advice can still be quoted


def test_wrong_crop_passage_is_never_quoted():
    hit = _hit("Spray against pink bollworm in cotton fields when moth catches rise above the economic threshold.", crop="cotton")
    c = compose("How to control bollworm in mango?", "en", [], [hit], crop="mango")
    assert c.abstain


def test_question_crop_overrides_field_crop():
    assert intents.resolve("How do I control pink bollworm in cotton?").crop == "cotton"
    assert intents.resolve("How do I control pink bollworm in cotton?").name == "pest_disease"
    assert intents.resolve("डाळिंबावरील तेलकट डाग रोगाचे नियंत्रण कसे करावे?").crop == "pomegranate"


def test_shared_fact_source_is_listed_once():
    """Found live: four facts from one forecast listed the same source four times."""
    src = {"label": "Open-Meteo", "url": "https://open-meteo.com", "fetched_at": None, "kind": "forecast"}
    facts = [Fact("Forecast", "3.2 °C", src), Fact("Threshold", "4.4 °C", src), Fact("Chance", "90%", src)]
    hit = _hit("Light irrigation before a frost night keeps the soil warm and protects mango flowers from frost injury.")
    c = compose("frost on mango tonight", "en", facts, [hit], intro="Forecast 3.2 °C.")
    assert [s["url"] for s in c.sources].count("https://open-meteo.com") == 1


def test_citation_and_heading_text_is_never_quoted():
    """Found live: 'Additional resources on energy balance Readers who want ... are referred to Rossi et al.' was quoted."""
    hit = _hit("Additional resources on energy balance Readers who want more detailed information on frost protection are "
               "referred to Rossi et al. Light irrigation before a frost night keeps the soil warm and protects flowers from frost.")
    c = compose("frost protection for mango", "en", [], [hit], intro="")
    assert not c.abstain and "et al" not in c.answer and "Readers" not in c.answer and "Light irrigation" in c.answer


def test_risk_intro_uses_the_localised_stage_name():
    from app.services.assistant import _stage_label

    assert _stage_label("mango", "flowering", "mr") == "मोहोर"
    assert _stage_label("mango", "flowering", "en") == "flowering"
    assert _stage_label("mango", None, "mr") == ""


def test_running_header_glued_into_a_sentence_is_never_quoted():
    """Found live: '... after the danger of freezing has 20 ]FROST PROTECTION: FUNDAMENTALS, PRACTICE AND ECONOMICS[ passed.'"""
    hit = _hit("Crops are transplanted to the field after the danger of freezing has 20 ]FROST PROTECTION: FUNDAMENTALS, PRACTICE "
               "AND ECONOMICS[ passed. Light irrigation before a frost night keeps the soil warm and protects flowers from frost.")
    c = compose("frost protection for mango", "en", [], [hit, _hit(hit.content, id=2, page=3)], intro="")
    assert "FUNDAMENTALS" not in c.answer and "Light irrigation" in c.answer
    assert sum(1 for s in c.sources if s["kind"] == "advisory") == 1        # two chunks of one document: cited once


def test_devanagari_from_a_pdf_is_never_quoted():
    """Audit 2026-11-02: legacy-font PDFs extract as garbled Devanagari ('२ न्मली' for '२ मिली'); a garbled dose is unsafe."""
    hit = _hit("डाळिंबाच्या बागेत फ्ल्युओपायरम चा वापर २ न्मली प्रती झाड प्रमाणे ड्रेंचिंग करावे म्हणजे सूत्रकृमींचे नियंत्रण होते. "
               "Light irrigation before a frost night keeps the soil warm and protects pomegranate flowers from frost.",
               crop="pomegranate", lang="mr", page=4)
    c = compose("डाळिंब दंव संरक्षण frost protection", "mr", [], [hit], intro="", crop="pomegranate")
    assert not c.abstain and "न्मली" not in c.answer and "Light irrigation" in c.answer


def test_heading_with_a_glued_list_marker_is_never_quoted():
    """Found in the eval: 'Land Preparation, pre-sowing agronomic practices and Input arrangements 1.' was quoted."""
    hit = _hit("Land Preparation, pre-sowing agronomic practices and Input arrangements 1. "
               "Farmers should prepare the land with one deep ploughing and two harrowings before sowing soybean.",
               crop="soybean")
    c = compose("land preparation before sowing soybean", "en", [], [hit], intro="", crop="soybean")
    assert not c.abstain and "arrangements 1." not in c.answer and "deep ploughing" in c.answer
