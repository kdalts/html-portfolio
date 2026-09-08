"""Generates and sends the daily report — the human-readable summary of
the day's Top N and how the pipeline run went.

Delivery is a generic webhook POST (`DAILY_REPORT_WEBHOOK_URL`) rather
than a specific vendor integration (email, Slack, ...): no credentials
for any specific provider were available to build and test against, and
a JSON webhook is what every mainstream chat/email-relay tool already
knows how to receive (Slack incoming webhooks, Discord, n8n's own
Webhook node, Zapier, ...). If no URL is configured, the report is
logged — a safe, functional default that never silently drops it.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.db.models.evaluation import DailyRanking
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Team

logger = logging.getLogger(__name__)

_UNSET = object()


def generate_daily_report(session: Session, ranking_date: date) -> str:
    home_team = aliased(Team)
    away_team = aliased(Team)

    rows = session.execute(
        select(DailyRanking, Fixture, home_team, away_team, League)
        .join(Fixture, Fixture.id == DailyRanking.fixture_id)
        .join(home_team, home_team.id == Fixture.home_team_id)
        .join(away_team, away_team.id == Fixture.away_team_id)
        .join(League, League.id == Fixture.league_id)
        .where(DailyRanking.ranking_date == ranking_date)
        .order_by(DailyRanking.rank)
    ).all()

    if not rows:
        return (
            f"Over 2.5 Daily Report — {ranking_date}\n\n"
            "No qualifying selections today — either no fixtures cleared the "
            "data-quality/confidence/league-reliability bar, or predictions haven't "
            "been generated yet."
        )

    lines = [
        f"Over 2.5 Daily Report — {ranking_date}",
        "Probability estimates, not guarantees. Confidence and market edge are separate figures.",
        "",
    ]
    for ranking, fixture, home, away, league in rows:
        edge_text = f"{ranking.edge:+.1%}" if ranking.edge is not None else "n/a"
        lines.append(
            f"{ranking.rank}. {home.name} vs {away.name} ({league.name}, "
            f"{fixture.kickoff.strftime('%Y-%m-%d %H:%M')} UTC) — "
            f"probability {ranking.final_probability:.1%}, confidence {ranking.confidence_score:.1%}, "
            f"edge {edge_text}"
        )
    return "\n".join(lines)


def send_report(report_text: str, *, webhook_url: str | None = _UNSET) -> bool:
    """Returns True if actually delivered to a webhook, False if only logged.

    `webhook_url` defaults to reading `get_settings().daily_report_webhook_url`
    (the normal CLI path) but can be passed explicitly — e.g. by
    run_daily_pipeline, which is handed a Settings object directly rather
    than relying on get_settings()'s process-wide env-var read, so it
    behaves correctly when called with test-injected settings. Pass
    `webhook_url=None` explicitly to force "log only" regardless of what's
    configured."""
    if webhook_url is _UNSET:
        webhook_url = get_settings().daily_report_webhook_url
    if not webhook_url:
        logger.info("Daily report (no DAILY_REPORT_WEBHOOK_URL configured, logging only):\n%s", report_text)
        return False

    try:
        response = httpx.post(webhook_url, json={"text": report_text}, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to deliver daily report to webhook: %s", exc)
        logger.info("Daily report (delivery failed, logging instead):\n%s", report_text)
        return False
    return True
