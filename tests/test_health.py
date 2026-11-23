from fastapi.testclient import TestClient
from api.main import create_app


def test_api_exposes_readiness(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", testing=True)) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["database"] == "ready"
