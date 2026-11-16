"""Domain vocabulary shared by retrieval (query expansion, tagging) and the voice layer (intents, DW-WER).

Loaded from data/terms_mr.json (PRD §8.2, §9.5). Each term maps vernacular forms (Marathi, Hindi,
romanised) to a canonical English key and a severity category used by DW-WER.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from app.core.config import DATA_DIR

TOPIC_KEYWORDS: dict[str, list[str]] = {
    # Storage words such as "chilling injury" or "low temperature storage" are deliberately excluded.
    "frost_protection": ["frost", "cold wave", "cold injury", "freez", "smudg", "दंव", "थंडीची लाट", "पाला", "शीतलहर", "ठंड से बचाव"],
    "heat_stress": ["heat", "high temperature", "heat wave", "sunburn", "scorching", "उष्णता", "उष्णतेची लाट", "लू", "गर्मी"],
    "rainfall_management": ["rain", "waterlogging", "drainage", "flood", "excess moisture", "पाऊस", "बारिश", "जलभराव"],
    "irrigation": ["irrigat", "drip", "water requirement", "basin", "furrow", "सिंचन", "पाणी", "सिंचाई"],
    "growth_stage": ["stage", "flowering", "fruit set", "pruning", "bud", "tillering", "squaring", "boll", "pod", "अवस्था", "फुलोरा"],
    "harvesting": ["harvest", "picking", "maturity", "काढणी", "तोडणी", "कटाई", "तुड़ाई"],
    "storage": ["storage", "post-harvest", "postharvest", "cold store", "ripening", "साठवण", "भंडारण"],
    "transport": ["transport", "packing", "packaging", "crate", "vehicle", "वाहतूक", "परिवहन"],
    "pest_disease": ["pest", "disease", "insect", "fungal", "blight", "mildew", "spray", "किड", "रोग", "कीट"],
    "cultivation": ["spacing", "planting", "sowing", "variety", "fertili", "manure", "nutrient", "लागवड", "पेरणी", "बुवाई"],
}


@lru_cache
def terms() -> dict[str, Any]:
    return json.loads((DATA_DIR / "terms_mr.json").read_text(encoding="utf-8"))


@lru_cache
def alias_index() -> dict[str, tuple[str, str]]:
    """lowercased alias -> (canonical, category)"""
    idx: dict[str, tuple[str, str]] = {}
    for cat, entries in terms()["categories"].items():
        for e in entries:
            for a in [e["canonical"], *e.get("aliases", [])]:
                idx[a.lower()] = (e["canonical"], cat)
    return idx


def expand_query(q: str) -> str:
    """Append canonical English terms for vernacular words so full-text search over English sources works."""
    low = q.lower()
    extra = []
    for alias, (canon, _) in alias_index().items():
        if len(alias) >= 2 and alias in low and canon.lower() not in low:
            extra.append(canon)
    return q if not extra else q + " " + " ".join(sorted(set(extra)))


def crop_terms() -> set[str]:
    return {a for a, (_, cat) in alias_index().items() if cat == "crop"}


def crops_in(text: str) -> set[str]:
    low = text.lower()
    out = set()
    for alias, (canon, cat) in alias_index().items():
        if cat == "crop" and re.search(rf"(?<![a-z]){re.escape(alias)}", low):
            out.add(canon)
    return out


def topics_in(text: str) -> set[str]:
    low = text.lower()
    return {t for t, kws in TOPIC_KEYWORDS.items() if any(k.lower() in low for k in kws)}


# Function words that carry no topic. Used by the full-text OR fallback (a question's "from" or "how" must not match
# every chunk) and by the composer's sentence picker.
STOPWORDS = frozenset("""
a an the and or of on in at to for from by with without into about as is are was were be been it its this that these those
what which who when where why how do does did can could should would will shall may might must i me my we our you your
there their they them he she his her any some all not no yes if then than so very also
kase kay
काय कसे कशी कसा करावे करावी करावा करू आहे आहेत आणि व किंवा च्या ची चे चा ला ना ने त मध्ये साठी वर का माझ्या माझे माझा माझी
क्या कैसे करें करूं है हैं और या के की का को में से पर लिए मेरी मेरे मेरा
""".split())

