"""Startup settings for local workspaces and a single-process hosted server."""
import os


def positive_int(name, default):
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return value


SERVER_MODE = os.getenv("AUREKA_SERVER_MODE", "0").lower() in {"1", "true", "yes"}
SECURE_COOKIES = os.getenv("AUREKA_SECURE_COOKIES", "0").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [s.strip() for s in os.getenv("AUREKA_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",") if s.strip()]
MAX_FILE_BYTES = positive_int("AUREKA_MAX_FILE_MB", 100) * 1024 * 1024
MAX_TOTAL_BYTES = positive_int("AUREKA_SESSION_INPUT_MB", 300) * 1024 * 1024
GLOBAL_INPUT_BYTES = positive_int("AUREKA_GLOBAL_INPUT_MB", 768) * 1024 * 1024
MAX_SESSIONS = positive_int("AUREKA_MAX_SESSIONS", 16)
SESSION_TTL = positive_int("AUREKA_SESSION_TTL", 3600)
