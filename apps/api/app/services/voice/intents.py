"""Deterministic intent resolution for the assistant (no model at inference). Keyword sets cover
English, Marathi, Hindi and common romanised forms."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.rag.vocab import alias_index

INTENT_KEYWORDS: dict[str, list[str]] = {
    "price": ["price", "rate", "mandi", "market", "sell", "भाव", "दर", "बाजार", "विक", "मंडी", "कीमत", "बेच", "bhav"],
    "transport": ["road", "route", "transport", "truck", "highway", "रस्ता", "मार्ग", "वाहतूक", "रास्ता", "सड़क", "खुला"],
    "frost": ["frost", "cold", "दंव", "थंडी", "पाला", "शीत", "ठंड"],
    "heat": ["heat", "hot", "temperature", "उष्ण", "तापमान", "गर्मी", "लू"],
    "rain": ["rain", "पाऊस", "बारिश", "वर्षा", "गारपीट"],
    "weather": ["weather", "forecast", "हवामान", "मौसम", "अंदाज"],
    "stage": ["stage", "flowering", "अवस्था", "फुलोरा", "मोहोर", "growth", "वाढ"],
    "pest_disease": ["pest", "disease", "insect", "spray", "worm", "borer", "mildew", "blight", "aphid", "thrips", "किड", "रोग",
                     "कीट", "फवारणी", "छिड़काव", "अळी", "डाग"],
    "action": ["what should i do", "what to do", "काय करावे", "काय करू", "क्या करूं", "क्या करें", "should i", "करावे"],
    "irrigation": ["irrigat", "water", "पाणी", "सिंचन", "सिंचाई", "पानी"],
    "harvest": ["harvest", "pick", "काढणी", "तोडणी", "कटाई", "तुड़ाई"],
}


# Questions about the farmer's own field ("what crop am I growing here", "what is this field"). They are answered
# from the field the farmer saved, never refused as off-topic.
FIELD_PHRASES = [
    "my field", "this field", "my farm", "this farm", "my plot", "this plot", "my land", "my crop", "which crop", "what crop",
    "growing here", "field details",
    "माझे शेत", "माझ्या शेत", "हे शेत", "या शेत", "माझे पीक", "माझ्या पिक", "कोणते पीक", "कुठले पीक", "माझी जमीन",
    "मेरा खेत", "मेरे खेत", "यह खेत", "इस खेत", "मेरी फसल", "मेरी फ़सल", "कौन सी फसल", "कौनसी फसल", "मेरी जमीन", "मेरी ज़मीन",
]
# A bare request for help or a greeting, matched as the whole question so "help me with my taxes" stays off-topic.
GENERIC_HELP = {
    "help", "help me", "i need help", "need help", "advice", "give me advice", "give advice", "advise me", "suggest", "suggestion",
    "guide me", "tell me", "what can you do", "hi", "hello", "hey", "namaste", "namaskar",
    "मदत", "मदत करा", "मला मदत करा", "मदत हवी आहे", "सल्ला", "सल्ला द्या", "नमस्कार", "हॅलो",
    "मदद", "मदद करो", "मदद करें", "मेरी मदद करो", "मेरी मदद करें", "मदद चाहिए", "सलाह", "सलाह दो", "सलाह दें", "नमस्ते", "हेलो",
}
FILLERS = {"please", "pls", "plz", "kindly", "sir", "कृपया", "जरा", "ज़रा"}
# Farm words with typos tolerated ("growin", "plantd"): any of them makes a question about the farm.
FARM_WORDS = re.compile(r"\b(grow\w*|grew|plant\w*|sow\w*|sown|crops?|fields?|farm\w*|plots?|orchard|vineyard|acre\w*|hectare\w*"
                        r"|prun\w*|variet\w*|yield\w*|soil|seeds?|fertili\w*|manure|spray\w*|stage)\b")
# Questions about the farmer's own account ("what is my name", "where is my farm"): answered from the profile.
PROFILE_PHRASES = ["my name", "who am i", "my account", "my profile", "my details", "about me", "where do i live",
                   "where is my farm", "where are my fields", "how many fields", "my location",
                   "माझे नाव", "माझं नाव", "मी कोण", "माझी माहिती", "किती शेत",
                   "मेरा नाम", "मैं कौन", "मेरी जानकारी", "कितने खेत"]
FARM_WORDS_DEVA = ["शेत", "पीक", "पिक", "लागवड", "बाग", "खेत", "फसल", "फ़सल", "उगा", "बोया", "बोई"]
# Punctuation only: a \W class would also strip Devanagari vowel signs.
_PUNCT = re.compile(r"[?!.,;:'\"()\[\]{}\u0964\u0965\u2026\-]+")


def _generic_help(low: str) -> bool:
    words = [w for w in _PUNCT.sub(" ", low).split() if w not in FILLERS]
    return " ".join(words) in GENERIC_HELP


CROP_ORDER = ("mango", "pomegranate", "grape", "soybean", "cotton", "sugarcane")


@dataclass(frozen=True)
class Intent:
    name: str          # primary intent
    crops: frozenset[str]
    signals: frozenset[str]
    agricultural: bool

    @property
    def crop(self) -> str | None:
        """The crop the question names (first in a fixed order if several), else None."""
        return next((c for c in CROP_ORDER if c in self.crops), None)


def resolve(text: str) -> Intent:
    low = text.lower()
    signals = {k for k, kws in INTENT_KEYWORDS.items() if any(w in low for w in kws)}
    if any(cat in ("pest", "disease", "chemical") and len(alias) > 3 and alias in low for alias, (_, cat) in alias_index().items()):
        signals.add("pest_disease")
    crops = frozenset(canon for alias, (canon, cat) in alias_index().items() if cat == "crop" and len(alias) > 2 and alias in low)
    agri_terms = any(cat in ("crop", "pest", "disease", "chemical", "stage", "weather", "market") and len(alias) > 2 and alias in low
                     for alias, (_, cat) in alias_index().items())
    if (any(p in low for p in FIELD_PHRASES) or _generic_help(low) or FARM_WORDS.search(low)
            or any(w in low for w in FARM_WORDS_DEVA)):
        signals.add("field_info")
    if any(p in low for p in PROFILE_PHRASES):
        signals.add("profile")
    agricultural = bool(signals or crops or agri_terms)
    # A specific topic wins over the general "about my field" (a frost question about my field is a frost question).
    order = ["price", "transport", "frost", "heat", "rain", "pest_disease", "harvest", "irrigation", "stage", "weather", "action", "profile", "field_info"]
    name = next((o for o in order if o in signals), "advisory" if agricultural else "outside_domain")
    return Intent(name, crops, frozenset(signals), agricultural)
