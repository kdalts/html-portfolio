"""Pure unit tests for backtest segmentation - no database."""

from app.backtest.segments import EvalRow, build_segment_results


def _row(fixture_id, y_true, y_prob, league_id=1, season_id=1, home_leaning=None):
    return EvalRow(
        fixture_id=fixture_id, y_true=y_true, y_prob=y_prob, league_id=league_id, season_id=season_id, home_leaning=home_leaning
    )


def test_empty_rows_produce_no_results_at_all():
    assert build_segment_results([]) == []


def test_overall_segment_always_present_when_rows_exist():
    rows = [_row(1, 1, 0.9)]
    results = build_segment_results(rows)
    overall = [r for r in results if r["segment_type"] == "overall"]
    assert len(overall) == 1
    assert overall[0]["segment_value"] == "ALL"
    assert overall[0]["sample_size"] == 1


def test_league_segmentation_groups_by_league_id():
    rows = [_row(1, 1, 0.9, league_id=10), _row(2, 0, 0.4, league_id=10), _row(3, 1, 0.6, league_id=20)]
    results = {(r["segment_type"], r["segment_value"]): r for r in build_segment_results(rows)}
    assert results[("league", "10")]["sample_size"] == 2
    assert results[("league", "20")]["sample_size"] == 1


def test_season_segmentation_groups_by_season_id():
    rows = [_row(1, 1, 0.9, season_id=2023), _row(2, 0, 0.4, season_id=2024)]
    results = {(r["segment_type"], r["segment_value"]): r for r in build_segment_results(rows)}
    assert results[("season", "2023")]["sample_size"] == 1
    assert results[("season", "2024")]["sample_size"] == 1


def test_probability_band_segmentation_excludes_sub_50_but_keeps_them_in_overall():
    rows = [_row(1, 1, 0.3), _row(2, 1, 0.62)]
    results = build_segment_results(rows)
    overall = next(r for r in results if r["segment_type"] == "overall")
    assert overall["sample_size"] == 2  # both rows count toward overall

    bands = {r["segment_value"]: r for r in results if r["segment_type"] == "probability_band"}
    assert "60-65" in bands
    assert bands["60-65"]["sample_size"] == 1
    assert sum(b["sample_size"] for b in bands.values()) == 1  # the 0.3 row never appears in any band


def test_home_away_segmentation():
    rows = [
        _row(1, 1, 0.9, home_leaning=True),
        _row(2, 0, 0.4, home_leaning=True),
        _row(3, 1, 0.6, home_leaning=False),
    ]
    results = {(r["segment_type"], r["segment_value"]): r for r in build_segment_results(rows)}
    assert results[("home_away", "home_leaning")]["sample_size"] == 2
    assert results[("home_away", "away_leaning")]["sample_size"] == 1


def test_rows_with_no_home_leaning_info_are_excluded_from_home_away_segment():
    rows = [_row(1, 1, 0.9, home_leaning=None)]
    results = build_segment_results(rows)
    home_away_rows = [r for r in results if r["segment_type"] == "home_away"]
    assert home_away_rows == []
    # but still counted elsewhere
    assert any(r["segment_type"] == "overall" for r in results)
