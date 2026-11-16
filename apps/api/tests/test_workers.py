"""Worker job state: idempotent per slot, failures recorded and retried (build brief Part 13)."""
from app.models.tables import JobRun
from app.workers.jobs import run_job


def test_job_runs_once_per_slot(db):
    calls = []
    assert run_job("demo", "slot-1", lambda s: calls.append(1) or {"n": 1}) == {"n": 1}
    assert run_job("demo", "slot-1", lambda s: calls.append(1) or {"n": 2}) is None   # already done for this slot
    assert len(calls) == 1
    row = db.query(JobRun).filter_by(job="demo", run_key="slot-1").one()
    assert row.status == "ok" and row.detail == {"n": 1}


def test_failed_job_is_recorded_then_retried(db):
    def boom(_):
        raise RuntimeError("upstream down")

    assert run_job("demo", "slot-2", boom) == {}
    db.expire_all()
    row = db.query(JobRun).filter_by(job="demo", run_key="slot-2").one()
    assert row.status == "failed" and "upstream down" in row.error
    assert run_job("demo", "slot-2", lambda s: {"ok": True}) == {"ok": True}
    db.expire_all()
    row = db.query(JobRun).filter_by(job="demo", run_key="slot-2").one()
    assert row.status == "ok" and row.attempts == 2


def test_health_reports_integrations(client):
    h = client.get("/api/v1/health").json()
    assert set(h["integrations"]) >= {"imd_api", "data_gov_in", "bhashini", "sms", "web_push", "whatsapp"}
    assert h["integrations"]["data_gov_in"] == "not_configured"
