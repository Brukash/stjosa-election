"""Vercel Python entry point for the FastAPI application."""
from __future__ import annotations

import os
import sys

# Make the backend package importable when Vercel runs the function from api/.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.main import app  # noqa: E402,F401

# Vercel's Python runtime serves the exported ASGI application.
