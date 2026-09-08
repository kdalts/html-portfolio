"""FastAPI application entrypoint.

Phase 1 exposes only health checks, including one that verifies the
Sportmonks connection is configured and reachable. Feature/prediction
endpoints are added in later phases once the database and models exist.
"""

import logging

from fastapi import FastAPI, HTTPException

from app.core.config import get_settings
from app.integrations.sportmonks.client import SportmonksClient
from app.integrations.sportmonks.exceptions import SportmonksError

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Football Over 2.5 Platform API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/health/sportmonks")
def sportmonks_health() -> dict:
    try:
        settings = get_settings()
    except Exception as exc:  # invalid/missing configuration
        raise HTTPException(status_code=503, detail=f"Sportmonks is not configured: {exc}") from exc

    client = SportmonksClient(settings)
    try:
        client.test_connection()
    except SportmonksError as exc:
        raise HTTPException(status_code=502, detail=f"Sportmonks connection failed: {exc}") from exc
    finally:
        client.close()

    return {"status": "ok", "provider": "sportmonks"}
