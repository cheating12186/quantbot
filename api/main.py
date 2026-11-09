"""QuantPilot FastAPI application; interactive docs are available at /docs."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agents.orchestrator import QuantPilotOrchestrator
from api.routes import backtesting, market, portfolio, research


def create_app(quantpilot: QuantPilotOrchestrator | None = None) -> FastAPI:
    application = FastAPI(
        title="QuantPilot API",
        version="1.0.0",
        description="Multi-agent quantitative research and deterministic paper trading. No real-money execution exists.",
    )
    application.state.quantpilot = quantpilot or QuantPilotOrchestrator()
    application.include_router(research.router)
    application.include_router(portfolio.router)
    application.include_router(backtesting.router)
    application.include_router(market.router)

    @application.get("/health", tags=["System"])
    def health():
        service = application.state.quantpilot
        return {
            "status": "ok",
            "paper_only": True,
            "groq_available": service.llm.available,
            "groq_model": service.settings.groq_model if service.llm.available else None,
            "database": service.database.engine.url.render_as_string(hide_password=True),
        }

    public_dir = Path(__file__).resolve().parents[1] / "public"
    if public_dir.exists():
        application.mount("/", StaticFiles(directory=public_dir, html=True), name="quantpilot-web")

    return application


app = create_app()
