import json
import httpx
from api import insights
from api.config import settings
from api.worker import run_one
from api import models as m


def test_provider_outage_keeps_numeric_evidence(client, monkeypatch):
    original_client = httpx.Client
    monkeypatch.setattr(settings,"ai_api_key","test-only-key")
    monkeypatch.setattr(settings,"ai_base_url","https://provider.test/v1")
    monkeypatch.setattr(settings,"ai_model","test-model")
    transport = httpx.MockTransport(lambda request: httpx.Response(503,json={"error":"unavailable"}))
    monkeypatch.setattr(insights.httpx,"Client",lambda **kwargs: original_client(transport=transport,**kwargs))
    result=client.post("/api/v1/insights/ask",json={"question":"Why did profit change?","language":"en"})
    assert result.status_code==200
    assert result.json()["provider_status"]=="fallback"
    assert result.json()["evidence"]
    assert client.get("/api/v1/reports/summary").status_code==200


def test_ai_provider_receives_aggregates_without_user_names(client,monkeypatch):
    original_client=httpx.Client
    monkeypatch.setattr(settings,"ai_api_key","test-only-key")
    monkeypatch.setattr(settings,"ai_base_url","https://provider.test/v1")
    monkeypatch.setattr(settings,"ai_model","test-model")
    bodies=[]
    def respond(request):
        bodies.append(request.content.decode())
        return httpx.Response(200,json={"choices":[{"message":{"content":"Consider reviewing discounts before changing prices."}}]})
    monkeypatch.setattr(insights.httpx,"Client",lambda **kwargs: original_client(transport=httpx.MockTransport(respond),**kwargs))
    response=client.post("/api/v1/insights/ask",json={"question":"Why did profit for privateperson@example.np change?","language":"en"})
    assert response.status_code==200
    assert response.json()["provider_status"]=="ai_assisted"
    assert "privateperson@example.np" not in bodies[0]
    assert "Test Traders" not in bodies[0]


def test_daily_ai_limit_preserves_numeric_insights(client,monkeypatch):
    monkeypatch.setattr(settings,"ai_daily_limit",1)
    assert client.post("/api/v1/insights/ask",json={"question":"What next?"}).status_code==200
    assert client.post("/api/v1/insights/ask",json={"question":"What next?"}).status_code==429
    assert client.get("/api/v1/insights").status_code==200


def test_durable_insight_job_is_tenant_scoped(client):
    job=client.post("/api/v1/jobs",json={"kind":"insights"}).json()
    assert run_one(client.app.state.session_factory)
    result=client.get(f"/api/v1/jobs/{job['id']}").json()
    assert result["status"]=="completed"
    assert result["result"]["metrics"]
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/register",json={"company":"Another business","name":"Another owner","email":"otherjobs@test.np","password":"Another-password!"})
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code==404


def test_background_job_rechecks_revoked_access(client):
    job=client.post("/api/v1/jobs",json={"kind":"insights"}).json()
    user_id=client.get("/api/v1/me").json()["id"]
    with client.app.state.session_factory.begin() as db:
        db.get(m.User,user_id).active=False
    assert run_one(client.app.state.session_factory)
    with client.app.state.session_factory() as db:
        assert db.get(m.Job,job["id"]).status=="failed"
