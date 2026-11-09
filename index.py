"""Vercel FastAPI entrypoint.

The FastAPI application is defined in api/main.py and assigned to the
top-level ``app`` name here — Vercel's FastAPI preset looks for an ``app``
instance at a recognized entrypoint. This file is selected explicitly via
``[tool.vercel] entrypoint`` in pyproject.toml; the repository-root
``app.py`` is the Streamlit dashboard, not this API, and is excluded from
the Vercel bundle via .vercelignore.
"""
from api.main import app as _fastapi_app

app = _fastapi_app

__all__ = ["app"]
