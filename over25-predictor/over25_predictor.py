#!/usr/bin/env python
"""
Over 2.5 Predictor -- main entry point.

Scans football fixtures for the next N days, pulls per-team stats, runs the
15-point checklist against each fixture, and writes/emails a CSV of the
results. See README.md for setup and the full column/check reference.

Usage:
    python over25_predictor.py [--days 7] [--leagues "Premier League,39"]
                                [--no-email] [--dry-run]

  --leagues   Comma-separated league names and/or ids to restrict to (for a
              cheap sanity-check run before going worldwide). Overrides
              LEAGUE_WHITELIST from config.
  --no-email  Build and save the CSV but skip sending the email.
  --dry-run   Alias for --no-email, kept for readability in ad-hoc runs.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime

from api_client import ApiFootballClient
from checks import MatchContext
from config import SETTINGS
from emailer import send_csv_email
from fixtures import fetch_fixtures_next_n_days
from logger_setup import setup_logging
from scoring import score_fixture, sort_rows, write_csv
from team_stats import attach_standings, fetch_team_season_stats, league_average_goals_per_game


def parse_args():
    parser = argparse.ArgumentParser(description="Over 2.5 Predictor")
    parser.add_argument("--days", type=int, default=None, help="Lookahead window in days (default from config)")
    parser.add_argument("--leagues", type=str, default=None, help="Comma-separated league names/ids to restrict to")
    parser.add_argument("--no-email", action="store_true", help="Skip sending the email")
    parser.add_argument("--dry-run", action="store_true", help="Alias for --no-email")
    return parser.parse_args()


def build_team_stats_cache():
    """Per-run in-memory cache keyed by (team_id, league_id, season) so a team
    playing twice in the window (cup replay etc.) isn't re-fetched."""
    cache: dict = {}

    def get(client, team_id, team_name, league_id, season):
        key = (team_id, league_id, season)
        if key not in cache:
            stats = fetch_team_season_stats(client, team_id, team_name, league_id, season)
            attach_standings(client, stats, league_id, season)
            cache[key] = stats
        return cache[key]

    return get


def build_league_avg_cache():
    cache: dict = {}

    def get(client, league_id, season):
        key = (league_id, season)
        if key not in cache:
            cache[key] = league_average_goals_per_game(client, league_id, season)
        return cache[key]

    return get


def main() -> int:
    args = parse_args()
    logger = setup_logging(SETTINGS.log_dir)

    started_at = datetime.now()
    logger.info("=" * 70)
    logger.info("Over 2.5 Predictor run starting at %s", started_at.isoformat(timespec="seconds"))

    problems = SETTINGS.validate_for_run()
    send_email = SETTINGS.send_email and not (args.no_email or args.dry_run)
    if problems:
        for problem in problems:
            # Email-related problems only block emailing, not the whole run.
            level = "warning" if "SEND_EMAIL" in problem else "error"
            getattr(logger, level)(problem)
        if not SETTINGS.api_key:
            logger.error("Cannot run without API_FOOTBALL_KEY. Aborting.")
            return 1
        if SETTINGS.send_email and (not SETTINGS.gmail_address or not SETTINGS.gmail_app_password):
            send_email = False

    days = args.days or SETTINGS.lookahead_days
    league_whitelist = SETTINGS.league_whitelist
    if args.leagues:
        league_whitelist = [item.strip() for item in args.leagues.split(",") if item.strip()]
    if league_whitelist:
        logger.info("League whitelist active (dry-run scope): %s", league_whitelist)

    client = ApiFootballClient(SETTINGS)
    team_stats_for = build_team_stats_cache()
    league_avg_for = build_league_avg_cache()

    matches_qualifying_high = 0
    rows = []
    errors = []

    try:
        fixtures = fetch_fixtures_next_n_days(client, days=days, league_whitelist=league_whitelist or None)

        for i, fixture in enumerate(fixtures, start=1):
            try:
                logger.info(
                    "[%d/%d] %s vs %s (%s, %s) on %s",
                    i, len(fixtures), fixture.home_team_name, fixture.away_team_name,
                    fixture.league_name, fixture.country, fixture.date,
                )

                home_stats = team_stats_for(
                    client, fixture.home_team_id, fixture.home_team_name, fixture.league_id, fixture.season
                )
                away_stats = team_stats_for(
                    client, fixture.away_team_id, fixture.away_team_name, fixture.league_id, fixture.season
                )

                if (home_stats.games_played or 0) < SETTINGS.min_games_played or (
                    away_stats.games_played or 0
                ) < SETTINGS.min_games_played:
                    logger.info(
                        "  -> excluded: insufficient sample size (home=%s, away=%s games played)",
                        home_stats.games_played, away_stats.games_played,
                    )
                    continue

                league_avg = league_avg_for(client, fixture.league_id, fixture.season)

                h2h_raw = client.head_to_head(fixture.home_team_id, fixture.away_team_id, last=3)
                h2h_totals = []
                for item in h2h_raw:
                    if item.get("fixture", {}).get("status", {}).get("short") != "FT":
                        continue
                    goals = item.get("goals", {})
                    if goals.get("home") is None or goals.get("away") is None:
                        continue
                    h2h_totals.append(goals["home"] + goals["away"])

                ctx = MatchContext(
                    home=home_stats,
                    away=away_stats,
                    min_games_played=SETTINGS.min_games_played,
                    recent_form_games=SETTINGS.recent_form_games,
                    h2h_totals=h2h_totals,
                    home_league_avg_goals=league_avg,
                    away_league_avg_goals=league_avg,
                    competition_type=fixture.competition_type,
                )

                row = score_fixture(fixture, ctx)
                rows.append(row)
                if row["checks_passed"] >= SETTINGS.high_score_threshold:
                    matches_qualifying_high += 1

            except Exception as exc:  # noqa: BLE001 - keep the run going for other fixtures
                logger.error(
                    "Error processing fixture %s vs %s: %s",
                    fixture.home_team_name, fixture.away_team_name, exc,
                )
                logger.debug(traceback.format_exc())
                errors.append(f"{fixture.home_team_name} vs {fixture.away_team_name}: {exc}")

        rows = sort_rows(rows)
        today_str = started_at.strftime("%Y-%m-%d")
        csv_path = write_csv(rows, SETTINGS.output_dir, f"over25_predictions_{today_str}.csv")

        if send_email and rows:
            subject = f"Over 2.5 Goals Predictions - {today_str} ({len(rows)} matches found)"
            body = (
                f"Over 2.5 Predictor run for {today_str}\n\n"
                f"Fixtures scanned: {len(fixtures)}\n"
                f"Matches with enough data to score: {len(rows)}\n"
                f"Matches scoring {SETTINGS.high_score_threshold}+ checks: {matches_qualifying_high}\n"
                f"API calls made this run: {client.call_count} (cache hits: {client.cache_hits})\n"
                f"Errors: {len(errors)}\n\n"
                f"See the attached CSV for the full, ranked list."
            )
            try:
                send_csv_email(
                    SETTINGS.smtp_host, SETTINGS.smtp_port, SETTINGS.gmail_address,
                    SETTINGS.gmail_app_password, SETTINGS.email_to, subject, body, csv_path,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send email: %s", exc)
                errors.append(f"email send failed: {exc}")
        elif not send_email:
            logger.info("Email sending skipped (--no-email/--dry-run or SEND_EMAIL=false).")
        elif not rows:
            logger.info("No qualifying rows -- skipping email.")

        duration = (datetime.now() - started_at).total_seconds()
        logger.info(
            "Run complete in %.1fs. Fixtures scanned=%d, scored=%d, high-score(%d+)=%d, "
            "API calls=%d, cache hits=%d, errors=%d",
            duration, len(fixtures), len(rows), SETTINGS.high_score_threshold,
            matches_qualifying_high, client.call_count, client.cache_hits, len(errors),
        )
        return 0 if not errors else 2

    except Exception as exc:  # noqa: BLE001 - top-level safety net for scheduled runs
        logger.error("Run failed: %s", exc)
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
