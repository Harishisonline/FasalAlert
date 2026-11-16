"""Assistant conversation history and Stop (docs/UX_QA_AUDIT.md ASK-08, ASK-09). Most tests replace the assistant
with a fixed TEST FIXTURE answer so they test saving and ownership, not retrieval; one uses the real pipeline."""
import pytest
from sqlalchemy import select

from app.models.tables import AskMessage, AskThread
from app.routers import misc
from app.services import conversations as conv
from tests.conftest import login

A, B = "+919876543210", "+919812345678"
FIXTURE = {"answer": "TEST FIXTURE answer.", "answer_audio_url": None, "cards": [{"label": "Chance", "value": "12%", "source": {"label": "x", "url": None, "fetched_at": None, "kind": "forecast"}}],
           "abstain": False, "sources": [], "asr_confidence": None, "dw_wer": None, "transcript": None, "low_confidence_terms": [],
           "abstain_reason": None, "kvk": None, "intent": "frost", "asks_remaining": 19, "stt_available": False}


@pytest.fixture
def fixed_answer(monkeypatch):
    calls = []

    def fake(db, user, text, audio_b64, field_id, locale, history=None):
        calls.append(text)
        fake.history = history
        return dict(FIXTURE)
    monkeypatch.setattr(misc.assistant, "ask", fake)
    return calls


def ask(client, who, text, **extra):
    return client.post("/api/v1/ask", json={"text": text, "locale": "en", **extra}, headers=who["headers"])


def test_first_question_starts_a_conversation_and_later_ones_join_it(client, db, fixed_answer):
    a = login(client, A)
    r = ask(client, a, "Is there frost risk for my grape plot near Niphad this week, and what should I do tonight?")
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == FIXTURE["answer"] and body["thread_id"]
    assert body["thread_title"].startswith("Is there frost risk") and body["thread_title"].endswith("…") and len(body["thread_title"]) <= 61
    assert body["user_message"]["role"] == "user" and body["assistant_message"]["response"]["cards"][0]["value"] == "12%"
    tid = body["thread_id"]
    r2 = ask(client, a, "And heavy rain?", thread_id=tid)
    assert r2.json()["thread_id"] == tid
    detail = client.get(f"/api/v1/ask/threads/{tid}", headers=a["headers"]).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][2]["content"] == "And heavy rain?"
    listed = client.get("/api/v1/ask/threads", headers=a["headers"]).json()
    assert [t["id"] for t in listed["items"]] == [tid] and listed["items"][0]["message_count"] == 4
    assert listed["items"][0]["snippet"] == FIXTURE["answer"]


def test_conversations_are_listed_newest_first_with_paging_and_search(client, db, fixed_answer):
    a = login(client, A)
    ids = [ask(client, a, q).json()["thread_id"] for q in ("Frost on grape", "Cotton pests", "Mandi price for soybean")]
    page = client.get("/api/v1/ask/threads", params={"limit": 2}, headers=a["headers"]).json()
    assert [t["id"] for t in page["items"]] == [ids[2], ids[1]] and page["next_cursor"]
    rest = client.get("/api/v1/ask/threads", params={"limit": 2, "cursor": page["next_cursor"]}, headers=a["headers"]).json()
    assert [t["id"] for t in rest["items"]] == [ids[0]] and rest["next_cursor"] is None
    found = client.get("/api/v1/ask/threads", params={"q": "cotton"}, headers=a["headers"]).json()
    assert [t["id"] for t in found["items"]] == [ids[1]]
    by_answer = client.get("/api/v1/ask/threads", params={"q": "fixture answer"}, headers=a["headers"]).json()
    assert len(by_answer["items"]) == 3


def test_rename_save_and_delete(client, db, fixed_answer):
    a = login(client, A)
    tid = ask(client, a, "Frost on grape").json()["thread_id"]
    r = client.patch(f"/api/v1/ask/threads/{tid}", json={"title": "  Grape   frost  ", "pinned": True}, headers=a["headers"])
    assert r.status_code == 200 and r.json()["title"] == "Grape frost" and r.json()["pinned"] is True
    assert client.patch(f"/api/v1/ask/threads/{tid}", json={"title": ""}, headers=a["headers"]).status_code == 400
    assert client.delete(f"/api/v1/ask/threads/{tid}", headers=a["headers"]).status_code == 204
    assert client.get(f"/api/v1/ask/threads/{tid}", headers=a["headers"]).status_code == 404
    db.expire_all()
    assert db.execute(select(AskMessage).where(AskMessage.thread_id == tid)).first() is None


def test_another_users_conversation_is_not_found(client, db, fixed_answer):
    a, b = login(client, A), login(client, B)
    tid = ask(client, a, "Frost on grape").json()["thread_id"]
    for call in (lambda: client.get(f"/api/v1/ask/threads/{tid}", headers=b["headers"]),
                 lambda: client.patch(f"/api/v1/ask/threads/{tid}", json={"pinned": True}, headers=b["headers"]),
                 lambda: client.delete(f"/api/v1/ask/threads/{tid}", headers=b["headers"]),
                 lambda: ask(client, b, "sneak in", thread_id=tid)):
        r = call()
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.get("/api/v1/ask/threads", headers=b["headers"]).json()["items"] == []
    assert len(client.get(f"/api/v1/ask/threads/{tid}", headers=a["headers"]).json()["messages"]) == 2


def test_stop_before_the_answer_is_ready_keeps_nothing(client, db, monkeypatch):
    """The farmer presses Stop while the answer is being worked out: nothing is saved, no conversation appears."""
    a = login(client, A)

    def stopped_midway(db_, user, text, audio_b64, field_id, locale, history=None):
        conv.mark_cancelled("req-stop-before-1")   # what POST /ask/cancel does while this request is still running
        return dict(FIXTURE)
    monkeypatch.setattr(misc.assistant, "ask", stopped_midway)
    body = ask(client, a, "Wrong question sent by mistake", request_id="req-stop-before-1").json()
    assert body["cancelled"] is True and body["thread_id"] is None and body["user_message"] is None
    assert client.get("/api/v1/ask/threads", headers=a["headers"]).json()["items"] == []


def test_stop_after_the_answer_was_saved_removes_it(client, db, fixed_answer):
    a = login(client, A)
    tid = ask(client, a, "Frost on grape", request_id="req-keep-0001").json()["thread_id"]
    ask(client, a, "Oops, wrong", thread_id=tid, request_id="req-stop-after-1")
    r = client.post("/api/v1/ask/cancel", json={"request_id": "req-stop-after-1"}, headers=a["headers"])
    assert r.status_code == 200 and r.json()["removed"] is True
    msgs = client.get(f"/api/v1/ask/threads/{tid}", headers=a["headers"]).json()["messages"]
    assert [m["content"] for m in msgs] == ["Frost on grape", FIXTURE["answer"]]
    # Stopping the only question of a conversation removes the conversation too.
    only = ask(client, a, "Mistake", request_id="req-stop-after-2").json()["thread_id"]
    client.post("/api/v1/ask/cancel", json={"request_id": "req-stop-after-2"}, headers=a["headers"])
    assert client.get(f"/api/v1/ask/threads/{only}", headers=a["headers"]).status_code == 404


def test_stop_cannot_remove_another_users_messages(client, db, fixed_answer):
    a, b = login(client, A), login(client, B)
    tid = ask(client, a, "Frost on grape", request_id="req-shared-001").json()["thread_id"]
    assert client.post("/api/v1/ask/cancel", json={"request_id": "req-shared-001"}, headers=b["headers"]).json()["removed"] is False
    assert len(client.get(f"/api/v1/ask/threads/{tid}", headers=a["headers"]).json()["messages"]) == 2


def test_an_unanswerable_voice_attempt_is_not_saved(client, db, monkeypatch):
    a = login(client, A)
    monkeypatch.setattr(misc.assistant, "ask", lambda *args, **kw: {**FIXTURE, "answer": "", "intent": "stt_unavailable"})
    body = client.post("/api/v1/ask", json={"audio_b64": "AAAA", "locale": "en"}, headers=a["headers"]).json()
    assert body["thread_id"] is None
    db.expire_all()
    assert db.execute(select(AskThread)).first() is None


def test_real_assistant_answer_is_saved_with_its_abstention(client, db):
    """The real pipeline: an off-topic question abstains, and the saved answer keeps the abstention."""
    a = login(client, A)
    body = ask(client, a, "Who won the cricket match yesterday?").json()
    assert body["abstain"] is True and body["thread_id"]
    saved = client.get(f"/api/v1/ask/threads/{body['thread_id']}", headers=a["headers"]).json()["messages"][1]
    assert saved["response"]["abstain"] is True and saved["response"]["abstain_reason"] == "outside_domain"
    assert saved["content"] == body["answer"]


def test_titles_are_the_first_words_of_the_question():
    assert conv.make_title("  Frost   on grape?  ") == "Frost on grape?"
    long = conv.make_title("माझ्या द्राक्ष बागेला या आठवड्यात दंवाचा धोका आहे का आणि आज रात्री मी काय करावे याबद्दल सांगा")
    assert long.endswith("…") and len(long) <= 61


def test_later_questions_carry_the_earlier_turns_without_off_topic_refusals(client, db, fixed_answer, monkeypatch):
    """ASK-13: the assistant reads follow-ups ("I mean my G spot field") with the conversation so far."""
    a = login(client, A)
    tid = ask(client, a, "What is growing here?").json()["thread_id"]
    refusal = {**FIXTURE, "answer": "I can only help with farming questions about your fields.", "abstain": True,
               "abstain_reason": "outside_domain", "intent": "outside_domain"}
    monkeypatch.setattr(misc.assistant, "ask", lambda *a_, **k: dict(refusal))
    ask(client, a, "What is growin here", thread_id=tid)
    seen = {}

    def capture(db_, user, text, audio_b64, field_id, locale, history=None):
        seen["history"] = history
        return dict(FIXTURE)
    monkeypatch.setattr(misc.assistant, "ask", capture)
    ask(client, a, "I am asking what I grow in my G spot field", thread_id=tid)
    turns = seen["history"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == "What is growing here?" and turns[2]["content"] == "What is growin here"
    assert all("only help with farming" not in t["content"] for t in turns)
