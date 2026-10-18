"""Hittar optimala byten med heltalsprogrammering (PuLP + HiGHS).

Modellen väljer en ny trupp som maximerar förväntade poäng över de kommande veckorna,
med optimal laguttagning och kapten varje vecka, under spelets regler:
positioner, budget, max 3 per lag och poängavdrag för extra byten.
"""

from __future__ import annotations

import pulp

from .model import Model
from .rules import (
    BENCH_WEIGHT,
    LINEUP_COMPOSITION,
    MAX_PER_CLUB,
    POSITIONS,
    SQUAD_COMPOSITION,
    TRANSFER_PENALTY,
)
from .squad import HORIZON_DISCOUNT, TeamState, evaluate_transfers

SOLVER_TIME_LIMIT = 20
MIN_GAIN = 0.1


def _candidate_pool(model: Model, state: TeamState, banned: set[str]) -> list[str]:
    """Alla spelare utom spärrade. Hela poolen behövs: billiga fynd som frigör budget
    till stjärnorna syns inte om man bara tittar på topplistor."""
    return [pid for pid in model.players if pid not in banned or pid in state.player_ids]


def optimize(
    model: Model,
    state: TeamState,
    horizon: int = 3,
    max_transfers: int = 1,
    free_card: bool = False,
    locked: set[str] | None = None,
    banned: set[str] | None = None,
) -> dict | None:
    locked = set(locked or ()) & set(state.player_ids)
    banned = set(banned or ()) - locked
    gws = model.horizon(horizon)
    if not gws:
        return None

    pool = _candidate_pool(model, state, banned)
    players = {pid: model.players[pid] for pid in pool}
    current = set(state.player_ids)
    budget = state.bank + sum(model.players[pid].price for pid in current if pid in model.players)

    prob = pulp.LpProblem("fantasy_shl", pulp.LpMaximize)
    x = {pid: prob.add_variable(f"x_{pid}", cat="Binary") for pid in pool}
    s = {(pid, gw): prob.add_variable(f"s_{pid}_{gw}", cat="Binary") for pid in pool for gw in gws}
    c = {(pid, gw): prob.add_variable(f"c_{pid}_{gw}", cat="Binary") for pid in pool for gw in gws}
    extra = prob.add_variable("extra_transfers", lowBound=0, cat="Integer")

    n_out = pulp.lpSum(1 - x[pid] for pid in current if pid in x)

    objective = []
    for i, gw in enumerate(gws):
        weight = HORIZON_DISCOUNT**i
        for pid, p in players.items():
            xp = p.xp.get(gw, 0.0) * weight
            objective.append(xp * (s[pid, gw] + c[pid, gw] + BENCH_WEIGHT * (x[pid] - s[pid, gw])))
    prob += pulp.lpSum(objective) - TRANSFER_PENALTY * extra

    for pos in POSITIONS:
        prob += pulp.lpSum(x[pid] for pid, p in players.items() if p.position == pos) == SQUAD_COMPOSITION[pos]
    for club in {p.club for p in players.values()}:
        prob += pulp.lpSum(x[pid] for pid, p in players.items() if p.club == club) <= MAX_PER_CLUB
    prob += pulp.lpSum(p.price * x[pid] for pid, p in players.items()) <= budget + 1e-6
    prob += n_out <= max_transfers
    if free_card:
        prob += extra == 0
    else:
        prob += extra >= n_out - min(state.free_transfers, 2)
    for pid in locked:
        prob += x[pid] == 1
    for gw in gws:
        for pos in POSITIONS:
            prob += pulp.lpSum(s[pid, gw] for pid, p in players.items() if p.position == pos) == LINEUP_COMPOSITION[pos]
        prob += pulp.lpSum(c[pid, gw] for pid in pool) == 1
        for pid in pool:
            prob += s[pid, gw] <= x[pid]
            prob += c[pid, gw] <= s[pid, gw]

    stats = prob.solve(pulp.HiGHS(msg=False, timeLimit=SOLVER_TIME_LIMIT))
    # Vid tidsgräns används bästa hittade lösning
    if not stats.has_solution:
        return None

    chosen = {pid for pid in pool if x[pid].value() > 0.5}
    out_ids = sorted(current - chosen, key=lambda pid: model.players[pid].position)
    in_ids = []
    # Para ihop in/ut per position så att listorna blir lättlästa
    remaining_in = sorted(chosen - current, key=lambda pid: model.players[pid].position)
    for pid in out_ids:
        match = next((i for i in remaining_in if model.players[i].position == model.players[pid].position), None)
        if match:
            in_ids.append(match)
            remaining_in.remove(match)
    in_ids.extend(remaining_in)

    evaluation = evaluate_transfers(model, state, out_ids, in_ids, horizon, free_card)
    return {"out": out_ids, "in": in_ids, **evaluation}


def suggest(
    model: Model,
    state: TeamState,
    horizon: int = 3,
    max_transfers: int = 3,
    free_card: bool = False,
    locked: set[str] | None = None,
    banned: set[str] | None = None,
) -> list[dict]:
    """Bästa förslag för 1..max_transfers byten (dubbletter tas bort)."""
    options = []
    seen = set()
    limits = [15] if free_card else range(1, max_transfers + 1)
    for k in limits:
        result = optimize(model, state, horizon, k, free_card, locked, banned)
        # Byten utan förväntad vinst (t.ex. två bänkspelare med 0 xP) är bara brus
        if not result or not result["out"] or result["net_gain"] <= MIN_GAIN:
            continue
        key = (tuple(sorted(result["out"])), tuple(sorted(result["in"])))
        if key in seen:
            continue
        seen.add(key)
        options.append(result)
    options.sort(key=lambda r: r["net_gain"], reverse=True)
    return options
