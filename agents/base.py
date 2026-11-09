"""Common agent execution wrapper: no exception can disappear silently."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from models.agent_outputs import ExecutionContext

T = TypeVar("T")


class BaseAgent:
    name = "Base Agent"

    def execute(self, context: ExecutionContext, operation: Callable[..., T], *args, **kwargs) -> T:
        with context.span(self.name) as span:
            return operation(*args, span=span, **kwargs)

    @staticmethod
    def require_complete(value: Any, name: str) -> Any:
        if value is None:
            raise RuntimeError(f"Required agent output missing: {name}")
        status = getattr(value, "status", None)
        if status and status.value == "FAILED":
            raise RuntimeError(f"Required agent failed: {name}")
        return value
