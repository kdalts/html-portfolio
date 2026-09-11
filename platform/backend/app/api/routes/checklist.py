from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.api.schemas import ChecklistEntry, ChecklistResponse
from app.db.models.checklist import ChecklistScore
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Team
from app.db.session import get_db

router = APIRouter(prefix="/api/checklist", tags=["checklist"])


@router.get("/daily", response_model=ChecklistResponse)
def get_daily_checklist(checklist_date: date, db: Session = Depends(get_db)) -> ChecklistResponse:
    """Every fixture kicking off on `checklist_date` that has a stored
    checklist score, sorted by score_pct descending (fixtures with no
    computable checks at all sort last, not first)."""
    home_team = aliased(Team)
    away_team = aliased(Team)
    start = datetime.combine(checklist_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(checklist_date, time.max, tzinfo=timezone.utc)

    rows = db.execute(
        select(ChecklistScore, Fixture, home_team, away_team, League)
        .join(Fixture, Fixture.id == ChecklistScore.fixture_id)
        .join(home_team, home_team.id == Fixture.home_team_id)
        .join(away_team, away_team.id == Fixture.away_team_id)
        .join(League, League.id == Fixture.league_id)
        .where(Fixture.kickoff >= start, Fixture.kickoff <= end)
        .order_by(ChecklistScore.score_pct.desc().nulls_last())
    ).all()

    entries = [
        ChecklistEntry(
            fixture_id=fixture.id,
            home_team=home.name,
            away_team=away.name,
            league_name=league.name,
            kickoff=fixture.kickoff,
            checks_passed=score.checks_passed,
            checks_computable=score.checks_computable,
            score_pct=score.score_pct,
            sample_size_ok=score.sample_size_ok,
            btts_rate_ok=score.btts_rate_ok,
            clean_sheet_rate_ok=score.clean_sheet_rate_ok,
            combined_goals_ok=score.combined_goals_ok,
            league_gap_ok=score.league_gap_ok,
            shots_on_target_ok=score.shots_on_target_ok,
            attack_defence_split_ok=score.attack_defence_split_ok,
            xg_ok=score.xg_ok,
            h2h_ok=score.h2h_ok,
            recent_form_ok=score.recent_form_ok,
            vs_league_avg_ok=score.vs_league_avg_ok,
            early_goals_ok=score.early_goals_ok,
            late_goals_ok=score.late_goals_ok,
            key_players_missing=score.key_players_missing,
            context_notes=score.context_notes,
            data_gaps=score.data_gaps,
            computed_at=score.computed_at,
        )
        for score, fixture, home, away, league in rows
    ]

    return ChecklistResponse(checklist_date=checklist_date, entries=entries)
