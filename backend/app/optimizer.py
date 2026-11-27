"""Hittar optimala byten med heltalsprogrammering (PuLP + HiGHS).

Modellen väljer en ny trupp som maximerar förväntade poäng över de kommande veckorna,
med optimal laguttagning och kapten varje vecka, under spelets regler:
positioner, budget, max 3 per lag och poängavdrag för extra byten.

optimize() gör byten inför nästa vecka. plan() planerar en byteskedja över flera veckor,
där gratisbyten sparas och förbrukas vecka för vecka, och svarar på om det lönar sig att
ta ett poängavdrag nu eller vänta på nästa gratisbyte.
"""

from __future__ import annotations

import pulp

from .model import Model
from .rules import (
    BENCH_WEIGHT,
    LINEUP_COMPOSITION,
    MAX_FREE_TRANSFERS,
    MAX_PER_CLUB,
    POSITIONS,
    SQUAD_COMPOSITION,
    TRANSFER_PENALTY,
)
from .squad import HORIZON_DISCOUNT, TeamState, best_lineup, evaluate_transfers, squad_value

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
    out_ids, in_ids = _pair(model, current - chosen, chosen - current)

    evaluation = evaluate_transfers(model, state, out_ids, in_ids, horizon, free_card)
    return {"out": out_ids, "in": in_ids, **evaluation}


def _pair(model: Model, outs: set[str], ins: set[str]) -> tuple[list[str], list[str]]:
    """Para ihop in/ut per position så att listorna blir lättlästa."""
    out_ids = sorted(outs, key=lambda pid: model.players[pid].position)
    in_ids = []
    remaining_in = sorted(ins, key=lambda pid: model.players[pid].position)
    for pid in out_ids:
        match = next((i for i in remaining_in if model.players[i].position == model.players[pid].position), None)
        if match:
            in_ids.append(match)
            remaining_in.remove(match)
    in_ids.extend(remaining_in)
    return out_ids, in_ids


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


# ---------------------------------------------------------------- byteskedja över flera veckor

PLAN_TAIL_WEEKS = 2  # veckor efter planen där truppen ligger still men fortfarande räknas
PLAN_POOL_TOP = 40  # kandidater per position efter xP
PLAN_POOL_VALUE = 15  # kandidater per position efter xP per miljon
# Ett byte ska ge minst så här mycket för att föreslås. Annars byter planen fram och tillbaka
# för tiondelar av en poäng, vilket bara är brus i en modell som missar med 4 poäng per vecka.
TRANSFER_FRICTION = 0.5
PLAN_TIME_LIMIT = 30


def _plan_pool(model: Model, state: TeamState, gws: list[int], banned: set[str]) -> list[str]:
    """Hela poolen blir för tung när varje spelare har variabler per vecka. Ta de bästa per
    position efter xP och efter xP per miljon (billiga spelare som frigör budget), plus truppen."""
    pool = set(state.player_ids)
    for pos in POSITIONS:
        cands = [p for p in model.players.values() if p.position == pos and p.id not in banned]
        by_xp = sorted(cands, key=lambda p: p.xp_over(gws), reverse=True)
        by_value = sorted(cands, key=lambda p: p.xp_over(gws) / max(p.price, 0.5), reverse=True)
        pool.update(p.id for p in by_xp[:PLAN_POOL_TOP])
        pool.update(p.id for p in by_value[:PLAN_POOL_VALUE])
    return [pid for pid in pool if pid in model.players]


def _free_transfer_walk(start: int, counts: list[int]) -> list[dict]:
    """Räknar gratisbyten vecka för vecka: 1 nytt per vecka, max 2 sparade."""
    ft = max(0, min(start, MAX_FREE_TRANSFERS))
    out = []
    for n in counts:
        used = min(n, ft)
        hits = n - used
        out.append({"free_before": ft, "transfers": n, "hits": hits, "penalty": hits * TRANSFER_PENALTY})
        ft = min(MAX_FREE_TRANSFERS, ft - used + 1)
    return out


def plan(
    model: Model,
    state: TeamState,
    weeks: int = 4,
    max_per_week: int = 2,
    allow_hits: bool = True,
    locked: set[str] | None = None,
    banned: set[str] | None = None,
) -> dict | None:
    """Planerar byten vecka för vecka över `weeks` veckor.

    Truppen får ändras inför var och en av de första `weeks` veckorna. Därefter räknas
    PLAN_TAIL_WEEKS veckor till med truppen orörd, så att byten sent i planen också måste
    löna sig efteråt och inte bara under en enda vecka.

    Gratisbyten följer reglerna: 1 per vecka, max 2 sparade, varje extra byte kostar 10.
    Det betyder att planen själv väger ett avdrag nu mot att vänta en vecka på nästa gratisbyte.
    """
    locked = set(locked or ()) & set(state.player_ids)
    banned = set(banned or ()) - locked
    gws = model.horizon(weeks + PLAN_TAIL_WEEKS)
    if not gws or not state.player_ids:
        return None
    n_transfer_weeks = min(weeks, len(gws))
    T = range(n_transfer_weeks)
    K = range(len(gws))
    sq = lambda k: min(k, n_transfer_weeks - 1)  # noqa: E731  truppens index för vecka k

    pool = _plan_pool(model, state, gws, banned)
    players = {pid: model.players[pid] for pid in pool}
    current = {pid for pid in state.player_ids if pid in players}
    budget = state.bank + sum(model.players[pid].price for pid in current)

    prob = pulp.LpProblem("fantasy_shl_plan", pulp.LpMaximize)
    x = {(p, t): prob.add_variable(f"x_{p}_{t}", cat="Binary") for p in pool for t in T}
    buy = {(p, t): prob.add_variable(f"b_{p}_{t}", cat="Binary") for p in pool for t in T}
    sell = {(p, t): prob.add_variable(f"o_{p}_{t}", cat="Binary") for p in pool for t in T}
    s = {(p, k): prob.add_variable(f"s_{p}_{k}", cat="Binary") for p in pool for k in K}
    c = {(p, k): prob.add_variable(f"c_{p}_{k}", cat="Binary") for p in pool for k in K}
    ft = {t: prob.add_variable(f"ft_{t}", lowBound=0, upBound=MAX_FREE_TRANSFERS, cat="Integer") for t in T}
    hits = {t: prob.add_variable(f"e_{t}", lowBound=0, cat="Integer") for t in T}
    n = {t: pulp.lpSum(buy[p, t] for p in pool) for t in T}

    objective = []
    for k, gw in enumerate(gws):
        weight = HORIZON_DISCOUNT**k
        t = sq(k)
        for pid, p in players.items():
            xp = p.xp.get(gw, 0.0) * weight
            if xp:
                objective.append(xp * (s[pid, k] + c[pid, k] + BENCH_WEIGHT * (x[pid, t] - s[pid, k])))
    prob += (
        pulp.lpSum(objective)
        - TRANSFER_PENALTY * pulp.lpSum(hits.values())
        - TRANSFER_FRICTION * pulp.lpSum(n.values())
    )

    clubs = {p.club for p in players.values()}
    for t in T:
        for pid in pool:
            before = (1 if pid in current else 0) if t == 0 else x[pid, t - 1]
            prob += x[pid, t] == before + buy[pid, t] - sell[pid, t]
            prob += buy[pid, t] + sell[pid, t] <= 1
        for pos in POSITIONS:
            prob += pulp.lpSum(x[pid, t] for pid, p in players.items() if p.position == pos) == SQUAD_COMPOSITION[pos]
        for club in clubs:
            prob += pulp.lpSum(x[pid, t] for pid, p in players.items() if p.club == club) <= MAX_PER_CLUB
        prob += pulp.lpSum(p.price * x[pid, t] for pid, p in players.items()) <= budget + 1e-6
        prob += n[t] <= max_per_week
        # Gratisbyten: de som används får inte vara fler än de som finns
        prob += hits[t] >= n[t] - ft[t]
        prob += hits[t] <= n[t]
        if not allow_hits:
            prob += hits[t] == 0
        if t == 0:
            prob += ft[t] == max(0, min(state.free_transfers, MAX_FREE_TRANSFERS))
        else:
            prob += ft[t] <= ft[t - 1] - (n[t - 1] - hits[t - 1]) + 1
        for pid in locked:
            prob += x[pid, t] == 1
    for k in K:
        t = sq(k)
        for pos in POSITIONS:
            prob += pulp.lpSum(s[pid, k] for pid, p in players.items() if p.position == pos) == LINEUP_COMPOSITION[pos]
        prob += pulp.lpSum(c[pid, k] for pid in pool) == 1
        for pid in pool:
            prob += s[pid, k] <= x[pid, t]
            prob += c[pid, k] <= s[pid, k]

    stats = prob.solve(pulp.HiGHS(msg=False, timeLimit=PLAN_TIME_LIMIT))
    if not stats.has_solution:
        return None

    squads: list[list[str]] = []
    moves: list[tuple[list[str], list[str]]] = []
    prev = list(state.player_ids)
    for t in T:
        chosen = {pid for pid in pool if x[pid, t].value() > 0.5}
        out_ids, in_ids = _pair(model, set(prev) - chosen, chosen - set(prev))
        moves.append((out_ids, in_ids))
        prev = [pid for pid in prev if pid not in out_ids] + in_ids
        squads.append(prev)

    walk = _free_transfer_walk(state.free_transfers, [len(o) for o, _ in moves])
    bank = state.bank
    week_rows = []
    for k, gw in enumerate(gws):
        t = sq(k)
        ids = squads[t]
        lineup = best_lineup(model, ids, gw)
        hold = best_lineup(model, state.player_ids, gw)
        row = {
            "gameweek": gw,
            "transfer_week": k < n_transfer_weeks,
            "out": [],
            "in": [],
            "free_before": None,
            "hits": 0,
            "penalty": 0,
            "expected_points": round(lineup.expected_points, 2),
            "hold_points": round(hold.expected_points, 2),
            "captain": lineup.captain.id if lineup.captain else None,
            "bank_after": round(bank, 2),
            "player_ids": ids,
        }
        if k < n_transfer_weeks:
            out_ids, in_ids = moves[k]
            bank += sum(model.players[p].price for p in out_ids) - sum(model.players[p].price for p in in_ids)
            row.update(
                out=out_ids,
                **{"in": in_ids},
                free_before=walk[k]["free_before"],
                hits=walk[k]["hits"],
                penalty=walk[k]["penalty"],
                bank_after=round(bank, 2),
            )
        week_rows.append(row)

    total_penalty = sum(w["penalty"] for w in week_rows)
    plan_xp = sum(w["expected_points"] for w in week_rows)
    hold_xp = sum(w["hold_points"] for w in week_rows)
    # Samma diskonterade värdering som optimeraren använder, för att kunna jämföra med "behåll laget"
    plan_value = sum(squad_value(model, squads[sq(k)], [gw]) * HORIZON_DISCOUNT**k for k, gw in enumerate(gws))
    hold_value = squad_value(model, state.player_ids, gws)
    return {
        "gameweeks": gws,
        "transfer_weeks": gws[:n_transfer_weeks],
        "weeks": week_rows,
        "transfers": sum(len(o) for o, _ in moves),
        "penalty": total_penalty,
        "xp_plan": round(plan_xp, 2),
        "xp_hold": round(hold_xp, 2),
        "xp_gain": round(plan_xp - hold_xp, 2),
        "net_gain": round(plan_xp - hold_xp - total_penalty, 2),
        "weighted_net_gain": round(plan_value - hold_value - total_penalty, 2),
        "final_player_ids": squads[-1],
        "free_transfers_after": _free_transfer_walk(state.free_transfers, [len(o) for o, _ in moves] + [0])[-1][
            "free_before"
        ],
    }
