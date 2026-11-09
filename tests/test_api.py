from fastapi.testclient import TestClient

from agents.orchestrator import QuantPilotOrchestrator
from api.main import create_app
from config.settings import Settings


def client(tmp_path):
    service = QuantPilotOrchestrator(Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}", data_provider="synthetic"))
    return TestClient(create_app(service))


def test_health_and_paper_portfolio(tmp_path):
    api = client(tmp_path)
    health = api.get("/health")
    assert health.status_code == 200
    assert health.json()["paper_only"] is True
    portfolio = api.get("/api/v1/paper/portfolio")
    assert portfolio.status_code == 200
    assert portfolio.json()["equity"] == 100000


def test_research_endpoint_persists_traceable_report(tmp_path):
    api = client(tmp_path)
    response = api.post("/api/v1/research", json={"ticker": "DEMO", "timeframe": "1d", "rows": 100, "auto_execute": False})
    assert response.status_code == 200
    report = response.json()
    assert report["outcome"] in ("APPROVED", "REJECTED", "NO_TRADE")
    assert report["traces"]
    run = api.get(f"/api/v1/research/runs/{report['run_id']}")
    assert run.status_code == 200
    assert run.json()["run_id"] == report["run_id"]


def test_backtest_endpoint_returns_computed_history(tmp_path):
    api = client(tmp_path)
    response = api.post("/api/v1/backtests", json={"ticker": "DEMO", "timeframe": "1d", "rows": 100, "config": {}})
    assert response.status_code == 200
    result = response.json()
    assert result["rows"] == 100
    assert len(result["equity_curve"]) == 99
    assert "next" not in result["methodology"] or "t+1" in result["methodology"]


def test_unknown_run_returns_404(tmp_path):
    api = client(tmp_path)
    assert api.get("/api/v1/research/runs/not-a-run").status_code == 404
