"""Groq drafting stays number-grounded; missing key falls back silently."""
from app.services.llm.grounded import allowed_number_tokens, draft_answer
from app.services.rag.compose import Fact


def test_draft_answer_rejects_invented_numbers(monkeypatch):
    from app.services.llm import grounded

    monkeypatch.setattr(grounded, "chat_completion", lambda messages: "Irrigate with 999 mm tonight.")
    facts = [Fact("Chance", "12%", {"label": "model", "url": None, "fetched_at": None, "kind": "model"})]
    allowed = allowed_number_tokens(facts, "Chance is 12%.", [], ["3", "64.5"])
    assert draft_answer('{"facts":[{"value":"12%"}]}', "en", "Should I irrigate?", allowed) is None


def test_draft_answer_accepts_grounded_numbers(monkeypatch):
    from app.services.llm import grounded

    monkeypatch.setattr(grounded, "chat_completion", lambda messages: "Frost chance is 12% tomorrow.")
    facts = [Fact("Chance", "12%", {"label": "model", "url": None, "fetched_at": None, "kind": "model"})]
    allowed = allowed_number_tokens(facts, "Frost chance is 12%.", [], [])
    assert draft_answer('{"facts":[{"value":"12%"}]}', "en", "Is there frost?", allowed) == "Frost chance is 12% tomorrow."
