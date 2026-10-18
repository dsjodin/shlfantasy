from collections import Counter

from app.rules import LINEUP_COMPOSITION
from app.squad import (
    TeamState,
    best_lineup,
    card_analysis,
    evaluate_transfers,
    is_valid,
    transfer_penalty,
    validate_squad,
)


def test_cheapest_squad_is_valid(model, state):
    issues = validate_squad(model, state.player_ids, state.bank)
    assert is_valid(issues), issues


def test_too_many_from_one_club(model, state):
    aaa = [p.id for p in model.players.values() if p.club == "AAA" and p.position == "F"]
    ids = [pid for pid in state.player_ids if model.players[pid].position != "F"] + aaa + [
        p.id for p in model.players.values() if p.club == "BBB" and p.position == "F"
    ][:1]
    issues = validate_squad(model, ids, 10)
    assert any("AAA" in i.message for i in issues if i.level == "error")


def test_negative_bank_is_error(model, state):
    assert not is_valid(validate_squad(model, state.player_ids, -0.1))


def test_missing_positions_reported(model, state):
    issues = validate_squad(model, state.player_ids[:-1], 0)
    assert not is_valid(issues)


def test_transfer_penalty():
    assert transfer_penalty(1, 1) == 0
    assert transfer_penalty(2, 1) == 10
    assert transfer_penalty(3, 2) == 10
    assert transfer_penalty(3, 0) == 30
    assert transfer_penalty(5, 1, free_card=True) == 0
    assert transfer_penalty(3, 5) == 10  # max 2 sparade


def test_lineup_composition_and_captain(model, state):
    lineup = best_lineup(model, state.player_ids, 2)
    assert Counter(p.position for p in lineup.starters) == LINEUP_COMPOSITION
    assert len(lineup.bench) == 4
    assert lineup.captain is max(lineup.starters, key=lambda p: p.xp[2])
    assert len(lineup.first_five) == 6


def test_evaluate_transfer_budget_and_gain(model, state):
    out = next(pid for pid in state.player_ids if model.players[pid].position == "F")
    # dyraste F i AAA (3 matcher vecka 2) som inte bryter lagregeln
    counts = Counter(model.players[pid].club for pid in state.player_ids if pid != out)
    candidates = [
        p
        for p in model.players.values()
        if p.position == "F" and p.id not in state.player_ids and counts.get(p.club, 0) < 3
    ]
    affordable = max(
        (p for p in candidates if p.price <= state.bank + model.players[out].price), key=lambda p: p.xp[2]
    )
    result = evaluate_transfers(model, state, [out], [affordable.id])
    assert result["valid"], result["issues"]
    assert result["bank_after"] == round(state.bank + model.players[out].price - affordable.price, 2)
    assert result["penalty"] == 0
    assert result["xp_gain_horizon"] > 0

    too_expensive = max(candidates, key=lambda p: p.price)
    poor = TeamState(state.player_ids, bank=0.0, free_transfers=0)
    result = evaluate_transfers(model, poor, [out], [too_expensive.id])
    assert not result["valid"]
    assert result["penalty"] == 10


def test_evaluate_rejects_unknown_out(model, state):
    outsider = next(p.id for p in model.players.values() if p.id not in state.player_ids)
    result = evaluate_transfers(model, state, [outsider], [outsider])
    assert not result["valid"]


def test_card_analysis_shape(model, state):
    weeks = card_analysis(model, state, 2)
    assert [w["gameweek"] for w in weeks] == [2, 3]
    cards = weeks[0]["cards"]
    assert set(cards) == {"toppa_laget", "anfall", "forsvar", "juniorer", "veteraner"}
    assert cards["juniorer"]["gain"] is None  # inga födelsedatum i testdatan
    assert cards["anfall"]["gain"] > 0
