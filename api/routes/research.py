from fastapi import APIRouter, Depends, HTTPException

from agents.orchestrator import QuantPilotOrchestrator
from api.dependencies import get_quantpilot
from models.agent_outputs import FinalReport
from models.trade import ResearchRequest

router = APIRouter(prefix="/api/v1/research", tags=["Multi-agent research"])


@router.post("", response_model=FinalReport, summary="Run the complete fail-closed agent workflow")
def research(request: ResearchRequest, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.run(request)


@router.get("/runs")
def run_history(limit: int = 50, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.runs(limit=min(max(limit, 1), 200))


@router.get("/runs/{run_id}")
def get_run(run_id: str, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    report = app.repository.get_run(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return report


@router.get("/traces")
def traces(run_id: str | None = None, app: QuantPilotOrchestrator = Depends(get_quantpilot)):
    return app.repository.traces(run_id)
