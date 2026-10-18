from app.backtest import build_weeks, evaluate, report
from app.projection import Params, expected_per_game, game_multiplier, team_strength

from .conftest import make_snapshot


def _game(home, away, hs, as_):
    return {"home": home, "away": away, "home_score": hs, "away_score": as_}


def test_team_strength_shrinks_towards_average():
    games = [_game("AAA", "BBB", 6, 0), _game("AAA", "BBB", 6, 0)]
    s = team_strength(games, prior_games=0)
    assert s.average == 3.0
    assert s.goals_against["BBB"] == 6.0
    shrunk = team_strength(games, prior_games=6)
    assert s.average < shrunk.goals_against["BBB"] < 6.0


def test_game_multiplier_directions():
    s = team_strength([_game("AAA", "BBB", 6, 0), _game("CCC", "DDD", 3, 3)], prior_games=0)
    p = Params(opponent_weight=0.5, gk_opponent_weight=0.5, home_advantage=0.05)
    # Mot BBB (släpper in mycket) blir det fler poäng för utespelare
    assert game_multiplier("F", "BBB", True, s, p) > game_multiplier("F", "AAA", True, s, p)
    # Målvakter tjänar på motståndare som gör få mål
    assert game_multiplier("GK", "BBB", True, s, p) > game_multiplier("GK", "AAA", True, s, p)
    assert game_multiplier("D", "CCC", True, s, p) > game_multiplier("D", "CCC", False, s, p)
    neutral = Params()
    assert game_multiplier("F", "BBB", True, s, neutral) == 1.0


def test_expected_per_game_prior_and_play_rate():
    p = Params(prior_strength=4, form_weight=0.0)
    new, rate = expected_per_game(price=8, games_played=0, ppg=0, form=0, team_games=0, prior=(0, 1), params=p)
    assert new == 8 and rate == 1.0
    backup, rate = expected_per_game(price=8, games_played=2, ppg=8, form=0, team_games=10, prior=(0, 1), params=p)
    assert rate < 0.3 and backup < 3


def _with_scores_and_history(snap):
    for i, g in enumerate(snap.games):
        if g["played"]:
            g["home_score"], g["away_score"] = 3 + i % 2, 2
    # vecka 1 spelad, vecka 2 "avslutad" med utfall
    snap.gameweeks[1]["status"] = "completed"
    for g in snap.games:
        if g["date"] < "2026-09-15":
            g["played"] = True
            g["home_score"], g["away_score"] = g.get("home_score") or 2, g.get("away_score") or 1
    snap.gameweek_points = {
        "1": {p["id"]: {"games": 4, "points": int(p["ppg"] * 4)} for p in snap.players},
        "2": {p["id"]: {"games": 1, "points": int(p["ppg"])} for p in snap.players},
    }
    return snap


def test_backtest_runs_on_synthetic_data():
    snap = _with_scores_and_history(make_snapshot())
    weeks = build_weeks(snap)
    assert [w.number for w in weeks] == [2]
    result = evaluate(weeks, Params())
    assert result["samples"] == len(snap.players)
    assert 0 < result["lineup_efficiency"] <= 1
    rep = report(snap)
    assert {m["key"] for m in rep["models"]} >= {"price_only", "current"}
