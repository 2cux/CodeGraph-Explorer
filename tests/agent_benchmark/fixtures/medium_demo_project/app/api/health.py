"""Health check endpoint."""

from app.config.settings import Settings


def health_check() -> dict:
    """Return service health status."""
    settings = Settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "debug": settings.debug,
    }
