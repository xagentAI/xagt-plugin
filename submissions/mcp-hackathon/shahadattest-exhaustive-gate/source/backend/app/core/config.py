import os

APP_NAME = "exhaustive-gate"
APP_VERSION = "0.1.0"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./exhaustive_gate.db")
GIT_COMMIT = os.getenv("GIT_COMMIT", "dev-local")
XAGENT_SLUG = os.getenv("XAGENT_SLUG", os.getenv("PROJECT_SLUG", "exhaustive-gate"))
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "524288"))
