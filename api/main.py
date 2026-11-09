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

    public_dir = _find_public_dir()
    if public_dir is not None:
        application.mount("/", StaticFiles(directory=public_dir, html=True), name="quantpilot-web")

    @application.get("/debug/fs", include_in_schema=False)
    def debug_fs():
        import os

        module_file = Path(__file__).resolve()
        return {
            "__file__": __file__,
            "resolved": str(module_file),
            "cwd": os.getcwd(),
            "candidates": [
                {"path": str(c), "exists": c.exists(), "entries": sorted(os.listdir(c)) if c.exists() else None}
                for c in _public_dir_candidates()
            ],
        }

    return application


def _public_dir_candidates():
    module_file = Path(__file__).resolve()
    return [
        module_file.parents[1] / "public",
        Path(__file__).resolve().parents[2] / "public" if len(module_file.parents) > 2 else module_file.parents[1] / "public",
        Path.cwd() / "public",
        Path("/var/task/public"),
        Path("/vercel/path0/public"),
    ]


def _find_public_dir():
    for candidate in _public_dir_candidates():
        if (candidate / "index.html").exists():
            return candidate
    return None


app = create_app()
