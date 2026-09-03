import os

APP_NAME = "mcp-doctor"
APP_VERSION = "0.1.0"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mcp_doctor.db")
ALLOW_PRIVATE_NETWORK = os.getenv("ALLOW_PRIVATE_NETWORK", "false").lower() == "true"
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
MAX_RESPONSE_BYTES = int(os.getenv("MAX_RESPONSE_BYTES", "1048576"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "524288"))
GIT_COMMIT = os.getenv("GIT_COMMIT", "dev-local")
PROJECT_SLUG = os.getenv("PROJECT_SLUG", "mcp-doctor")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
