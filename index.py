"""Vercel FastAPI entrypoint.

The FastAPI application is defined in api/main.py and re-exported here so the
project root has the top-level ``app`` object that Vercel's FastAPI preset
loads. This file is selected explicitly via ``[tool.vercel] entrypoint`` in
pyproject.toml; the repository-root ``app.py`` is the Streamlit dashboard,
not this API.
"""
from api.main import app

__all__ = ["app"]
