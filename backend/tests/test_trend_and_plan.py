from collections import Counter

from app import optimizer
from app.projection import DEFAULT_PARAMS, expected_per_game
from app.rules import MAX_PER_CLUB, SQUAD_COMPOSITION
from app.squad import TeamState, card_analysis, card_plan
from app.trend import WeekStat, compute, recent_play_rate

# ---------------------------------------------------------------- trend


def _weeks(rows):
    return [WeekStat(i + 1, g, p, t) for i, (g, p, t) in enumerate(rows)]


def test_trend_up_on_hot_streak():
    t = compute(_weeks([(2, 6, 2), (2, 6, 2), (2, 6, 2), (2, 14, 2), (2, 16, 2)]), 1.0)
    assert t.direction == "up"
    assert t.recent_ppg > t.season_ppg


def test_trend_down_when_losing_ice_time():
    t = compute(_weeks([(2, 8, 2), (2, 8, 2), (2, 8, 2), (1, 4, 2), (0, 0, 2)]), 1.0)
    assert t.direction == "down"
    assert "mindre" in t.reason
    assert t.recent_play_rate < t.season_play_rate


def test_trend_flat_with_too_few_games():
    assert compute(_weeks([(1, 20, 1), (1, 0, 1)]), 1.0).direction == "flat"


def test_recent_play_rate_weights_latest_week():
    weeks = _weeks([(2, 0, 2), (2, 0, 2), (0, 0, 2)])
    assert recent_play_rate(weeks, 1.0) < 0.5


def test_pdo_correction_lowers_plus_minus_heavy_player():
    from dataclasses import replace

    params = replace(DEFAULT_PARAMS, pdo_weight=1.0)
    args = {"price": 8.0, "games_played": 10, "ppg": 6.0, "form": 6.0, "team_games": 10, "prior": (1.0, 0.5), "params": params}
    lucky, _ = expected_per_game(**args, pm_per_game=2.0)
    neutral, _ = expected_per_game(**args, pm_per_game=0.0)
    assert lucky < neutral


def test_model_exposes_trend(model):
    p = next(iter(model.players.values()))
    assert p.trend.direction in ("up", "down", "flat")


# ---------------------------------------------------------------- kortplan


def _card_week(gw, gains, used=()):
    return {"gameweek": gw, "cards": {k: {"name": k, "gain": g, "used": k in used} for k, g in gains.items()}}


def test_card_plan_one_card_per_week():
    # Båda korten är bäst vecka 1, men bara ett får spelas den veckan
    weeks = [
        _card_week(1, {"anfall": 10.0, "forsvar": 9.0}),
        _card_week(2, {"anfall": 6.0, "forsvar": 2.0}),
    ]
    plan = card_plan(weeks, [])
    assert len({p["gameweek"] for p in plan}) == len(plan)
    assert {(p["gameweek"], p["card"]) for p in plan} == {(1, "forsvar"), (2, "anfall")}


def test_card_plan_skips_used_and_blocked():
    weeks = [_card_week(1, {"anfall": 10.0, "forsvar": 9.0}), _card_week(2, {"anfall": 5.0, "forsvar": 4.0})]
    plan = card_plan(weeks, ["anfall"], blocked_weeks={1})
    assert [(p["gameweek"], p["card"]) for p in plan] == [(2, "forsvar")]


def test_card_plan_from_real_analysis(model, state):
    weeks = card_analysis(model, state, 2)
    plan = card_plan(weeks, ["toppa_laget"])
    assert all(p["card"] != "toppa_laget" for p in plan)
    assert len({p["gameweek"] for p in plan}) == len(plan)


# ---------------------------------------------------------------- byteskedja


def _check(model, ids, budget):
    players = [model.players[pid] for pid in ids]
    assert Counter(p.position for p in players) == SQUAD_COMPOSITION
    assert max(Counter(p.club for p in players).values()) <= MAX_PER_CLUB
    assert sum(p.price for p in players) <= budget + 1e-6


def test_plan_respects_rules_every_week(model, state):
    budget = state.bank + sum(model.players[p].price for p in state.player_ids)
    result = optimizer.plan(model, state, weeks=2, max_per_week=2)
    assert result is not None
    for w in result["weeks"]:
        _check(model, w["player_ids"], budget)
        assert w["bank_after"] >= -1e-6
        assert len(w["out"]) == len(w["in"]) <= 2
    assert result["net_gain"] >= 0


def test_plan_without_hits_uses_only_free_transfers(model):
    from tests.conftest import cheapest_valid_squad

    state = TeamState(player_ids=cheapest_valid_squad(model), bank=5.0, free_transfers=0)
    result = optimizer.plan(model, state, weeks=2, max_per_week=2, allow_hits=False)
    assert result["penalty"] == 0
    first = result["weeks"][0]
    assert first["free_before"] == 0 and first["out"] == []
    # Vecka två har ett nytt gratisbyte
    assert len(result["weeks"][1]["out"]) <= 1


def test_free_transfer_walk():
    walk = optimizer._free_transfer_walk(0, [2, 0, 1, 3])
    assert [w["free_before"] for w in walk] == [0, 1, 2, 2]
    assert [w["penalty"] for w in walk] == [20, 0, 0, 10]


# ---------------------------------------------------------------- kategorimodellen


def test_category_model_trusts_ice_time_but_not_luck():
    from dataclasses import replace

    from app.projection import categories_complete, category_means, category_ppg

    means = category_means(
        [
            ("F", {"time_on_ice_points": 20, "goals_points": 8, "plus_minus_points": 0}, 10),
            ("F", {"time_on_ice_points": 20, "goals_points": 8, "plus_minus_points": 0}, 10),
        ]
    )["F"]
    params = replace(DEFAULT_PARAMS, category_model=True)
    base = category_ppg({"time_on_ice_points": 20, "goals_points": 8}, 10, means, params)
    more_ice = category_ppg({"time_on_ice_points": 30, "goals_points": 8}, 10, means, params)
    more_goals = category_ppg({"time_on_ice_points": 20, "goals_points": 18}, 10, means, params)
    lucky = category_ppg({"time_on_ice_points": 20, "goals_points": 8, "plus_minus_points": 10}, 10, means, params)
    # Lika stor skillnad i poäng: istid slår igenom mer än mål, plus/minus inte alls
    assert more_ice - base > more_goals - base > 0
    assert abs(lucky - base) < 1e-9
    assert categories_complete({"time_on_ice_points": 20, "goals_points": 8}, 28)
    assert not categories_complete({}, 28)


def test_model_falls_back_without_categories(model):
    # Testdatan saknar poängfördelning, så modellen ska använda poäng per match som vanligt
    assert all(p.xp_per_game > 0 for p in model.players.values())


# ---------------------------------------------------------------- istid från matchrapporter


def test_parse_boxscore_reads_toi_per_player():
    from app.sources.shl import parse_boxscore, parse_toi

    data = {
        "stats": {
            "homeTeamValue": [{"TOI": "13:47", "info": {"playerId": 2388}}, {"TOI": "0:00", "info": {"playerId": 1}}],
            "awayTeamValue": [{"TOI": "20:05", "info": {"playerId": 4135}}],
        }
    }
    assert parse_boxscore(data) == {"2388": 827, "4135": 1205}
    assert parse_toi("bad") == 0
    assert parse_boxscore({}) == {}


def test_toi_trend_raises_xp_and_direction():
    from app.trend import toi_by_week, toi_ratio

    toi = toi_by_week({"g1": {"7": 600}, "g2": {"7": 600}, "g3": {"7": 900}, "g4": {"7": 900}}, {"g1": 1, "g2": 1, "g3": 2, "g4": 3})
    assert toi["7"] == {1: (1200, 2), 2: (900, 1), 3: (900, 1)}
    weeks = [WeekStat(w, n, 5 * n, n, 0, *toi["7"][w]) for w, n in ((1, 2), (2, 1), (3, 1))]
    ratio = toi_ratio(weeks)
    assert ratio is not None and ratio > 1.15
    trend = compute(weeks, 1.0)
    assert trend.direction == "up" and "istid" in trend.reason
    args = {"price": 8.0, "games_played": 4, "ppg": 5.0, "form": 5.0, "team_games": 4, "prior": (1.0, 0.5), "params": DEFAULT_PARAMS}
    assert expected_per_game(**args, toi_ratio=ratio)[0] > expected_per_game(**args)[0]
    # Begränsat så att en konstig rapport inte slår för hårt
    assert expected_per_game(**args, toi_ratio=5.0)[0] <= expected_per_game(**args)[0] * 1.5 + 1e-9


def test_toi_trend_needs_recent_games():
    from app.trend import toi_ratio

    weeks = [WeekStat(1, 4, 20, 4, 0, 4 * 900, 4), WeekStat(2, 0, 0, 2), WeekStat(3, 0, 0, 2)]
    assert toi_ratio(weeks) is None
