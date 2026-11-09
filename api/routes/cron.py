"""Autopilot tick entrypoint for scheduled or scripted agent cycles.

GET is used because Vercel Cron issues GET requests. Every cycle runs the
complete deterministic multi-agent workflow and records an AUTOPILOT_TICK
journal event. Execution remains paper-only and fail-closed: if OANDA data
is stale or any control fails, no order is placed.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from agents.orchestrator import QuantPilotOrchestrator
from api.dependencies import get_quantpilot
from models.trade import ResearchRequest

router = APIRouter(prefix="/api/v1/cron", tags=["Autopilot"])

DEFAULT_OBJECTIVE = (
    "Run the complete multi-agent workflow for the configured instrument. "
    "Trade only when every deterministic control passes; otherwise reject."
)


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@router.get("/tick", summary="Run one full agent workflow cycle (paper-only)")
def cron_tick(request: Request, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    secret = os.environ.get("CRON_SECRET", "").strip()
    if secret:
        authorization = request.headers.get("authorization", "")
        if authorization != f"Bearer {secret}":
            raise HTTPException(status_code=401, detail="Invalid cron secret")

    symbol = os.environ.get("AUTOPILOT_SYMBOL", "EUR_USD").strip().upper()
    timeframe = os.environ.get("AUTOPILOT_TIMEFRAME", "1h").strip().lower()
    objective = os.environ.get("AUTOPILOT_OBJECTIVE", DEFAULT_OBJECTIVE).strip()
    auto_execute = _flag("AUTOPILOT_EXECUTE", True)

    try:
        report = app.run(
            ResearchRequest(
                ticker=symbol,
                timeframe=timeframe,
                request=objective,
                auto_execute=auto_execute,
                rows=300,
            )
        )
    except Exception as exc:
        try:
            app.repository.log("AUTOPILOT_ERROR", {"symbol": symbol, "timeframe": timeframe, "error": str(exc)[:500]})
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Autopilot cycle failed: {exc}") from exc

    app.repository.log(
        "AUTOPILOT_TICK",
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "outcome": report.outcome.value,
            "run_id": report.run_id,
            "auto_execute": auto_execute,
            "traces": len(report.traces),
        },
    )
    return {
        "run_id": report.run_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "outcome": report.outcome.value,
        "reasons": report.reasons,
        "auto_execute": auto_execute,
        "execution": report.execution.model_dump(mode="json") if report.execution else None,
        "traces": len(report.traces),
    }
