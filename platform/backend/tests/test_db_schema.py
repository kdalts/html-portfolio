"""Structural checks on the ORM metadata. No database connection needed —
these validate the Python model definitions directly."""

from app.db.models import Base
from app.db.models.evaluation import MODEL_TYPES, PROBABILITY_BANDS, SEGMENT_TYPES
from app.db.models.features import FEATURE_CONTEXTS, ROLLING_WINDOWS, STAT_KEYS, _team_feature_column_names

REQUIRED_TABLES = {
    "leagues",
    "teams",
    "seasons",
    "fixtures",
    "match_statistics",
    "match_xg",
    "sportmonks_predictions",
    "odds",
    "team_features",
    "match_features",
    "model_predictions",
    "backtest_results",
    "league_model_performance",
    "daily_rankings",
}


def test_all_required_tables_exist():
    assert REQUIRED_TABLES == set(Base.metadata.tables.keys())


def test_every_table_has_a_primary_key():
    for name, table in Base.metadata.tables.items():
        assert len(table.primary_key.columns) >= 1, f"{name} has no primary key"


def test_every_table_has_timestamps():
    for name, table in Base.metadata.tables.items():
        assert "created_at" in table.columns, f"{name} missing created_at"
        assert "updated_at" in table.columns, f"{name} missing updated_at"


def test_every_table_has_at_least_one_index_or_unique_constraint():
    # Every table beyond its primary key should have some secondary access
    # path (an index or unique constraint) - a proxy for "queryable at scale".
    for name, table in Base.metadata.tables.items():
        has_index = len(table.indexes) > 0
        has_unique = any(c.unique for c in table.constraints if hasattr(c, "unique"))
        has_extra_constraint = len(table.constraints) > 1  # more than just the PK
        assert has_index or has_unique or has_extra_constraint, f"{name} has no secondary index/constraint"


def test_fixtures_required_columns():
    columns = set(Base.metadata.tables["fixtures"].columns.keys())
    required = {
        "id",
        "league_id",
        "season_id",
        "kickoff",
        "home_team_id",
        "away_team_id",
        "home_goals",
        "away_goals",
        "total_goals",
        "over_2_5",
        "status",
    }
    assert required <= columns


def test_fixtures_foreign_keys_point_at_expected_tables():
    fixtures = Base.metadata.tables["fixtures"]
    fk_targets = {fk.column.table.name for fk in fixtures.foreign_keys}
    assert fk_targets == {"leagues", "seasons", "teams"}


def test_fixture_child_tables_cascade_on_fixture_delete():
    cascading_children = [
        "match_statistics",
        "match_xg",
        "sportmonks_predictions",
        "odds",
        "team_features",
        "match_features",
        "model_predictions",
        "daily_rankings",
    ]
    for table_name in cascading_children:
        table = Base.metadata.tables[table_name]
        fixture_fks = [fk for fk in table.foreign_keys if fk.column.table.name == "fixtures"]
        assert fixture_fks, f"{table_name} has no FK to fixtures"
        assert all(fk.ondelete == "CASCADE" for fk in fixture_fks), (
            f"{table_name}.fixture_id should CASCADE on fixture delete"
        )


def test_team_features_has_expected_generated_columns():
    expected = set(_team_feature_column_names())
    # 10 stats x 3 windows x 2 contexts + 6 sample-size columns = 66
    assert len(expected) == len(STAT_KEYS) * len(ROLLING_WINDOWS) * len(FEATURE_CONTEXTS) + len(
        ROLLING_WINDOWS
    ) * len(FEATURE_CONTEXTS)
    actual = set(Base.metadata.tables["team_features"].columns.keys())
    assert expected <= actual


def test_probability_bands_cover_50_to_100():
    assert PROBABILITY_BANDS == ("50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80+")


def test_model_types_include_every_probability_source():
    assert set(MODEL_TYPES) == {"poisson", "ml", "sportmonks", "raw_ensemble", "final"}


def test_segment_types_cover_required_slices():
    # league, season, probability band, home/away, plus an overall baseline
    assert set(SEGMENT_TYPES) == {"overall", "league", "season", "probability_band", "home_away"}


def test_model_predictions_distinguishes_probability_confidence_and_edge():
    columns = set(Base.metadata.tables["model_predictions"].columns.keys())
    assert "final_probability" in columns
    assert "confidence_score" in columns
    assert "edge" in columns
    # they must be genuinely separate columns, not aliases of one another
    assert len({"final_probability", "confidence_score", "edge"}) == 3
