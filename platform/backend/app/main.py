"""FastAPI application entrypoint.

Health checks (Phase 1) plus the read API (Phase 12) the Next.js
dashboard consumes: daily rankings, match detail, league performance,
model performance, and historical backtest results. Every endpoint here
is read-only — nothing in this app accepts writes; all data is produced
by the CLI pipelines documented in docs/SETUP.md and Phase 13's
automation. See docs/API.md for the full endpoint reference.
"""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import backtest, fixtures, leagues, models, rankings, system
from app.core.config import get_settings
from app.integrations.sportmonks.client import SportmonksClient
from app.integrations.sportmonks.exceptions import SportmonksError

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Football Over 2.5 Platform API", version="0.1.0")

try:
    _cors_origins = [origin.strip() for origin in get_settings().cors_allowed_origins.split(",") if origin.strip()]
except Exception:  # noqa: BLE001 - Settings() not configured yet (e.g. import-time in a fresh env); CORS just stays empty
    _cors_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(rankings.router)
app.include_router(fixtures.router)
app.include_router(leagues.router)
app.include_router(models.router)
app.include_router(backtest.router)
app.include_router(system.router)


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
