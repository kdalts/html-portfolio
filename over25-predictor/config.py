"""
Configuration loader for the Over 2.5 Predictor.

Values are read from environment variables, optionally loaded from a local
`.env` file (via python-dotenv) or a local `config.json` file. Real secrets
(API keys, email app password) must NEVER be committed to git -- `.env` and
`config.json` are both listed in .gitignore.

Precedence: real environment variables > .env file > config.json > defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    # python-dotenv not installed yet -- config.json / real env vars still work.
    pass

_CONFIG_JSON_PATH = BASE_DIR / "config.json"
_json_config: dict = {}
if _CONFIG_JSON_PATH.exists():
    try:
        _json_config = json.loads(_CONFIG_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"config.json is not valid JSON: {exc}") from exc


def _get(key: str, default=None):
    if key in os.environ:
        return os.environ[key]
    if key in _json_config:
        return _json_config[key]
    return default


def _get_bool(key: str, default: bool) -> bool:
    val = _get(key, None)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _get_int(key: str, default: int) -> int:
    val = _get(key, None)
    if val is None or val == "":
        return default
    return int(val)


def _get_float(key: str, default: float) -> float:
    val = _get(key, None)
    if val is None or val == "":
        return default
    return float(val)


def _get_list(key: str, default: list) -> list:
    val = _get(key, None)
    if val is None or val == "":
        return default
    if isinstance(val, list):
        return val
    return [item.strip() for item in str(val).split(",") if item.strip()]


@dataclass
class Settings:
    # --- API-Football ---
    api_provider: str = field(default_factory=lambda: _get("API_PROVIDER", "direct"))  # "direct" or "rapidapi"
    api_key: str = field(default_factory=lambda: _get("API_FOOTBALL_KEY", ""))
    api_timezone: str = field(default_factory=lambda: _get("API_TIMEZONE", "Europe/London"))

    # --- Run behaviour ---
    lookahead_days: int = field(default_factory=lambda: _get_int("LOOKAHEAD_DAYS", 7))
    min_games_played: int = field(default_factory=lambda: _get_int("MIN_GAMES_PLAYED", 5))
    recent_form_games: int = field(default_factory=lambda: _get_int("RECENT_FORM_GAMES", 5))
    # Lookback used for checks 12/13 (first/last 15-min goals) -- capped small
    # by default because it costs one extra API call per historical match.
    timing_lookback_games: int = field(default_factory=lambda: _get_int("TIMING_LOOKBACK_GAMES", 10))
    min_timing_sample: int = field(default_factory=lambda: _get_int("MIN_TIMING_SAMPLE", 5))
    league_whitelist: list = field(default_factory=lambda: _get_list("LEAGUE_WHITELIST", []))
    high_score_threshold: int = field(default_factory=lambda: _get_int("HIGH_SCORE_THRESHOLD", 10))

    # --- Rate limiting / caching ---
    requests_per_minute: int = field(default_factory=lambda: _get_int("REQUESTS_PER_MINUTE", 60))
    cache_ttl_hours: int = field(default_factory=lambda: _get_int("CACHE_TTL_HOURS", 12))
    cache_dir: str = field(default_factory=lambda: _get("CACHE_DIR", str(BASE_DIR / "cache")))
    fetch_xg: bool = field(default_factory=lambda: _get_bool("FETCH_XG", True))
    fetch_injuries: bool = field(default_factory=lambda: _get_bool("FETCH_INJURIES", True))

    # --- Output ---
    output_dir: str = field(default_factory=lambda: _get("OUTPUT_DIR", str(Path.home() / "Desktop" / "Football Bets")))
    log_dir: str = field(default_factory=lambda: _get("LOG_DIR", str(BASE_DIR)))

    # --- Email ---
    send_email: bool = field(default_factory=lambda: _get_bool("SEND_EMAIL", True))
    smtp_host: str = field(default_factory=lambda: _get("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: _get_int("SMTP_PORT", 587))
    gmail_address: str = field(default_factory=lambda: _get("GMAIL_ADDRESS", ""))
    gmail_app_password: str = field(default_factory=lambda: _get("GMAIL_APP_PASSWORD", ""))
    email_to: str = field(default_factory=lambda: _get("EMAIL_TO", "kdalts@googlemail.com"))

    @property
    def api_base_url(self) -> str:
        if self.api_provider == "rapidapi":
            return "https://api-football-v1.p.rapidapi.com/v3"
        return "https://v3.football.api-sports.io"

    @property
    def api_headers(self) -> dict:
        if self.api_provider == "rapidapi":
            return {
                "x-rapidapi-key": self.api_key,
                "x-rapidapi-host": "api-football-v1.p.rapidapi.com",
            }
        return {"x-apisports-key": self.api_key}

    def validate_for_run(self) -> list:
        """Return a list of human-readable problems, empty if OK to run."""
        problems = []
        if not self.api_key:
            problems.append(
                "API_FOOTBALL_KEY is not set. Copy .env.example to .env and fill it in "
                "(get a key from https://www.api-football.com/ or your RapidAPI dashboard)."
            )
        if self.send_email and (not self.gmail_address or not self.gmail_app_password):
            problems.append(
                "SEND_EMAIL is true but GMAIL_ADDRESS / GMAIL_APP_PASSWORD are not set. "
                "Generate an app password at https://myaccount.google.com/apppasswords "
                "and put it in .env, or set SEND_EMAIL=false to skip emailing."
            )
        return problems


SETTINGS = Settings()
