"""Vercel's supported FastAPI entrypoint; also runnable with uvicorn app:app."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "source"))
from life_exchange_rate.main import app
