from collections import Counter

from app import optimizer
from app.rules import MAX_PER_CLUB, SQUAD_COMPOSITION
from app.squad import TeamState, squad_value


def _check_squad(model, ids, budget):
    players = [model.players[pid] for pid in ids]
    assert Counter(p.position for p in players) == SQUAD_COMPOSITION
    assert max(Counter(p.club for p in players).values()) <= MAX_PER_CLUB
    assert sum(p.price for p in players) <= budget + 1e-6


def test_build_from_scratch_respects_rules(model):
    result = optimizer.optimize(model, TeamState([], 100.0, 0), horizon=2, max_transfers=15, free_card=True)
    assert result is not None and result["valid"], result and result["issues"]
    _check_squad(model, result["new_player_ids"], 100.0)


def test_suggest_improves_and_respects_limits(model, state):
    budget = state.bank + sum(model.players[p].price for p in state.player_ids)
    options = optimizer.suggest(model, state, horizon=2, max_transfers=3)
    assert options
    best = options[0]
    assert best["valid"]
    assert len(best["out"]) == len(best["in"]) <= 3
    _check_squad(model, best["new_player_ids"], budget)
    assert best["net_gain"] > 0
    gws = model.horizon(2)
    assert squad_value(model, best["new_player_ids"], gws) > squad_value(model, state.player_ids, gws)


def test_single_transfer_limit_and_keep(model, state):
    keep = set(state.player_ids)
    assert optimizer.suggest(model, state, horizon=2, max_transfers=2, locked=keep) == []
    result = optimizer.optimize(model, state, horizon=2, max_transfers=1)
    assert len(result["out"]) <= 1


def test_avoid_list(model, state):
    first = optimizer.optimize(model, state, horizon=2, max_transfers=1)
    bought = set(first["in"])
    second = optimizer.optimize(model, state, horizon=2, max_transfers=1, banned=bought)
    assert not bought & set(second["in"])
