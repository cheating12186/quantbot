from fastapi import Request

from agents.orchestrator import QuantPilotOrchestrator


def get_quantpilot(request: Request) -> QuantPilotOrchestrator:
    return request.app.state.quantpilot
