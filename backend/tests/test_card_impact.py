"""Coachkort i bytesutvärderingen och i optimeringen (punkt 4).

All data är konstruerad: spelare, födelsedatum och matcher sätts i testerna."""

import copy

import pulp
import pytest

from app import optimizer
from app.model import build_model
from app.rules import LINEUP_COMPOSITION, POSITIONS
from app.squad import TeamState, best_lineup, card_analysis, card_analysis_for, evaluate_transfers, same_squad

from .conftest import cheapest_valid_squad, make_snapshot

ALL_CARDS = ["toppa_laget", "anfall", "forsvar", "juniorer", "veteraner"]


def _with_birthdates(snap, veterans=(), juniors=()):
    for i, pid in enumerate(veterans):
        snap.athletes[f"v{i}"] = {"player_id": pid, "birth_date": "1990-01-01"}  # 36 år
    for i, pid in enumerate(juniors):
        snap.athletes[f"j{i}"] = {"player_id": pid, "birth_date": "2008-01-01"}  # 18 år
    return snap


def _setup_veteran_swap(card_gain_matters: bool):
    """Trupp med en startande veteranback och en något bättre back utanför truppen.
    Allt annat är låst eller spärrat, så det enda möjliga bytet är veteran -> alternativ."""
    snap = make_snapshot()
    model = build_model(snap)
    squad = cheapest_valid_squad(model)
    gw = model.next_gameweek
    lineup = best_lineup(model, squad, gw)
    veteran = max((p for p in lineup.starters if p.position == "D"), key=lambda p: p.xp.get(gw, 0)).id
    vet_raw = next(p for p in snap.players if p["id"] == veteran)
    # Samma lag och position, så att matcherna är desamma och bara poängsnittet skiljer
    alt_raw = next(
        p for p in snap.players if p["position"] == "D" and p["id"] not in squad and p["club"] == vet_raw["club"]
    )
    # Alternativet är lite bättre: samma pris, något högre poängsnitt
    alt_raw.update(price=vet_raw["price"], ppg=vet_raw["ppg"] + 0.3, form=vet_raw["form"] + 0.3, games_played=vet_raw["games_played"])
    alt_raw["total_points"] = int(alt_raw["ppg"] * alt_raw["games_played"])
    _with_birthdates(snap, veterans=[veteran])
    model = build_model(snap)
    used = [c for c in ALL_CARDS if c != "veteraner"] if card_gain_matters else ALL_CARDS
    state = TeamState(squad, 5.0, 1, used)
    locked = set(squad) - {veteran}
    banned = {p for p in model.players if p not in squad and p != alt_raw["id"]}
    return model, state, veteran, alt_raw["id"], locked, banned


# ---------------------------------------------------------------- 4a: exakt kortvärde


def test_selling_veteran_lowers_veteran_card_value():
    model, state, veteran, alt, _, _ = _setup_veteran_swap(card_gain_matters=True)
    result = evaluate_transfers(model, state, [veteran], [alt], horizon=2)
    vet = result["cards"]["per_card"]["veteraner"]
    assert vet["before"] is not None and vet["before"]["gain"] > 0
    assert vet["change"] < 0
    assert result["net_gain_incl_cards"] == pytest.approx(result["net_gain"] + result["cards"]["change"], abs=0.02)


def test_swap_without_age_effect_leaves_age_cards_unchanged():
    snap = make_snapshot()
    model = build_model(snap)
    squad = cheapest_valid_squad(model)
    _with_birthdates(snap, veterans=[squad[0]], juniors=[squad[1]])
    model = build_model(snap)
    state = TeamState(squad, 20.0, 1, [])
    pos = model.players[squad[-1]].position
    out = next(pid for pid in squad[2:] if model.players[pid].position == pos)
    counts = {}
    for pid in squad:
        counts[model.players[pid].club] = counts.get(model.players[pid].club, 0) + 1
    into = next(
        p.id for p in model.players.values() if p.position == pos and p.id not in squad and counts.get(p.club, 0) < 3
    )
    result = evaluate_transfers(model, state, [out], [into], horizon=2)
    for key in ("juniorer", "veteraner"):
        assert result["cards"]["per_card"][key]["change"] == pytest.approx(0.0)


def test_used_cards_are_not_counted():
    model, state, veteran, alt, _, _ = _setup_veteran_swap(card_gain_matters=False)
    result = evaluate_transfers(model, state, [veteran], [alt], horizon=2)
    assert result["cards"]["per_card"] == {}
    assert result["cards"]["change"] == 0
    assert result["net_gain_incl_cards"] == result["net_gain"]


def test_card_analysis_is_unchanged_by_refactor(model, state):
    weeks = model.horizon(2)
    assert card_analysis(model, state, 2) == card_analysis_for(model, same_squad(state.player_ids, weeks), state.used_cards)


# ---------------------------------------------------------------- 4b: korten i MIP:en


def test_mip_keeps_veteran_when_card_is_worth_more_than_the_swap():
    model, state, veteran, alt, locked, banned = _setup_veteran_swap(card_gain_matters=True)
    kept = optimizer.optimize(model, state, horizon=2, max_transfers=1, locked=locked, banned=banned)
    assert veteran in kept["new_player_ids"]
    assert any(c["card"] == "veteraner" for c in kept["card_schedule"])

    model, state, veteran, alt, locked, banned = _setup_veteran_swap(card_gain_matters=False)
    sold = optimizer.optimize(model, state, horizon=2, max_transfers=1, locked=locked, banned=banned)
    assert sold["out"] == [veteran] and sold["in"] == [alt]


def test_each_card_once_and_one_card_per_week():
    snap = make_snapshot()
    model = build_model(snap)
    squad = cheapest_valid_squad(model)
    _with_birthdates(snap, veterans=squad[:2], juniors=squad[2:4])
    model = build_model(snap)
    for used in ([], ["anfall", "toppa_laget"]):
        result = optimizer.plan(model, TeamState(squad, 5.0, 1, used), weeks=2)
        sched = result["card_schedule"]
        assert len({c["gameweek"] for c in sched}) == len(sched)
        assert len({c["card"] for c in sched}) == len(sched)
        assert not {c["card"] for c in sched} & set(used)
        assert result["net_gain_incl_cards"] == pytest.approx(result["net_gain"] + result["cards"]["change"], abs=0.02)


def _lineup_mip(model, ids, gw, schedule, monkeypatch):
    """Laguttagning för en låst trupp en vecka, med kortet i schemat. Utan reservvärde,
    så att målfunktionen bara är veckans poäng."""
    monkeypatch.setattr(optimizer, "_reserve_values", lambda *a, **k: ({}, {}, {}))
    players = {pid: model.players[pid] for pid in ids}
    prob = pulp.LpProblem("t", pulp.LpMaximize)
    s = {(pid, gw): prob.add_variable(f"s_{pid}", cat="Binary") for pid in ids}
    c = {(pid, gw): prob.add_variable(f"c_{pid}", cat="Binary") for pid in ids}
    state = TeamState(ids, 0.0, 1, [])
    terms, cv = optimizer._add_cards(prob, model, state, players, [(gw, gw, 1.0)], s, c, lambda pid: 1, schedule=schedule)
    prob += pulp.lpSum(p.xp.get(gw, 0.0) * (s[pid, gw] + c[pid, gw]) for pid, p in players.items()) + pulp.lpSum(terms)
    for pos in POSITIONS:
        prob += pulp.lpSum(s[pid, gw] for pid, p in players.items() if p.position == pos) == LINEUP_COMPOSITION[pos]
    prob += pulp.lpSum(c.values()) == 1 - cv.toppa.get(gw, 0)
    for pid in ids:
        prob += c[pid, gw] <= s[pid, gw]
    prob.solve(pulp.HiGHS(msg=False))
    captains = sum(v.value() for v in c.values())
    return pulp.value(prob.objective), captains


@pytest.mark.parametrize("card", ["anfall", "forsvar", "toppa_laget", "veteraner"])
def test_mip_card_bonus_matches_exact_card_analysis(card, monkeypatch):
    snap = make_snapshot()
    model = build_model(snap)
    squad = cheapest_valid_squad(model)
    _with_birthdates(snap, veterans=squad[:3])
    model = build_model(snap)
    gw = model.next_gameweek
    normal = best_lineup(model, squad, gw).expected_points
    exact = card_analysis_for(model, {gw: squad}, [])[0]["cards"][card]["gain"]
    value, captains = _lineup_mip(model, squad, gw, frozenset({(gw, card)}), monkeypatch)
    assert value - normal == pytest.approx(exact, abs=0.02)
    assert captains == pytest.approx(0 if card == "toppa_laget" else 1)  # ingen kapten med Toppa Laget


def test_card_saved_when_later_week_is_better():
    snap = make_snapshot()
    # Vecka 3 får tre matcher för alla lag, så kort är värda mer då än vecka 2
    clubs = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    for day in ("2026-09-17", "2026-09-19"):
        for a, b in zip(clubs[::2], clubs[1::2]):
            snap.games.append({**copy.deepcopy(snap.games[-1]), "id": f"{day}-{a}-{b}", "date": day, "home": a, "away": b})
    model = build_model(snap)
    squad = cheapest_valid_squad(model)
    state = TeamState(squad, 5.0, 1, ["toppa_laget", "forsvar", "juniorer", "veteraner"])
    result = optimizer.optimize(model, state, horizon=1, max_transfers=1)
    assert not any(c["card"] == "anfall" for c in result["card_schedule"])  # sparas till vecka 3
    assert result["card_reserve"].get("anfall", 0) > 0
