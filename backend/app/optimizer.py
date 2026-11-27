"""Hittar optimala byten med heltalsprogrammering (PuLP + HiGHS).

Modellen väljer en ny trupp som maximerar förväntade poäng över de kommande veckorna,
med optimal laguttagning och kapten varje vecka, under spelets regler:
positioner, budget, max 3 per lag och poängavdrag för extra byten.

optimize() gör byten inför nästa vecka. plan() planerar en byteskedja över flera veckor,
där gratisbyten sparas och förbrukas vecka för vecka, och svarar på om det lönar sig att
ta ett poängavdrag nu eller vänta på nästa gratisbyte.

Båda tar med coachkorten (_add_cards): vilket kort som spelas vilken vecka väljs tillsammans
med truppen, och ett kort som sparas har ett värde. Därmed undviker optimeringen att sälja
t.ex. en veteran inför ett Veteraner-kort som lönar sig.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

import pulp

from .model import Model, Player
from .rules import (
    BENCH_WEIGHT,
    COACH_CARDS,
    FIRST_FIVE_COMPOSITION,
    LINEUP_COMPOSITION,
    MAX_FREE_TRANSFERS,
    MAX_PER_CLUB,
    POSITIONS,
    SQUAD_COMPOSITION,
    TRANSFER_PENALTY,
)
from .squad import (
    CARD_IMPACT_WEEKS,
    HORIZON_DISCOUNT,
    TeamState,
    best_lineup,
    card_analysis_for,
    card_impact,
    card_plan,
    evaluate_transfers,
    is_junior,
    is_veteran,
    same_squad,
    squad_value,
)

SOLVER_TIME_LIMIT = 20
MIN_GAIN = 0.1


# ---------------------------------------------------------------- coachkort i MIP:en

DOUBLING_CARDS = ("anfall", "forsvar", "juniorer", "veteraner")
MIP_CARDS = DOUBLING_CARDS + ("toppa_laget",)


def _gw_day(model: Model, gw: int) -> date:
    info = model.gameweek(gw)
    return date.fromisoformat(info["start"]) if info else date.today()


def _eligible(card: str, p: Player, day: date) -> bool:
    if card == "anfall":
        return p.position == "F"
    if card == "forsvar":
        return p.position == "D"
    if card == "juniorer":
        return is_junior(p, day)
    if card == "veteraner":
        return is_veteran(p, day)
    return False


@dataclass
class CardVars:
    """Kortvariablerna i en MIP, för att kunna läsa ut lösningen."""

    y: dict[tuple[str, Any], Any] = field(default_factory=dict)  # (kort, veckonyckel) -> binär
    week_of: dict[Any, int] = field(default_factory=dict)  # veckonyckel -> matchvecka
    toppa: dict[Any, Any] = field(default_factory=dict)  # veckonyckel -> y för Toppa Laget (för kaptenen)
    reserve: dict[str, float] = field(default_factory=dict)  # kortets värde om det sparas (nuvarande trupp)

    def schedule(self) -> list[dict]:
        def on(var: Any) -> bool:
            value = var if isinstance(var, (int, float)) else var.value()
            return value is not None and value > 0.5

        out = [
            {"gameweek": self.week_of[k], "card": card, "name": COACH_CARDS[card]}
            for (card, k), var in self.y.items()
            if on(var)
        ]
        return sorted(out, key=lambda c: c["gameweek"])


def _reserve_values(
    model: Model,
    state: TeamState,
    players: dict[str, Player],
    after_gws: list[int],
    first_gw: int,
    cards: list[str],
) -> tuple[dict[str, dict[str, float]], dict[str, float], dict[str, int]]:
    """Vad varje kort är värt om det sparas till veckorna efter horisonten.

    Kortets bästa vecka w* efter horisonten tas fram med nuvarande trupp. För dubblingskort
    blir värdet linjärt i den sista truppen: varje behörig spelare som redan finns i truppen
    bidrar med sin xP den veckan om han startar, annars med vad dubbleringen tjänar på att
    han tar en plats (2·xP minus den svagaste startspelaren på positionen). En såld veteran
    sänker alltså värdet av ett sparat Veteraner-kort, men köp belönas inte för kort långt
    fram. Det bortser från samspel mellan flera behöriga spelare på samma position.
    Toppa Laget får ett fast värde.
    Allt diskonteras med HORIZON_DISCOUNT för avståndet, som resten av målfunktionen.
    """
    per_player: dict[str, dict[str, float]] = {}
    constant: dict[str, float] = {}
    best_week: dict[str, int] = {}
    if not after_gws or not state.player_ids:
        return per_player, constant, best_week
    analysis = card_analysis_for(model, same_squad(state.player_ids, after_gws), state.used_cards)
    order = [gw["number"] for gw in model.gameweeks]
    for card in cards:
        weeks = [(w["gameweek"], w["cards"][card]["gain"]) for w in analysis if w["cards"][card]["gain"] is not None]
        if not weeks:
            continue
        gw, gain = max(weeks, key=lambda t: t[1])
        if gain <= 0:
            continue
        best_week[card] = gw
        disc = HORIZON_DISCOUNT ** (order.index(gw) - order.index(first_gw))
        if card == "toppa_laget":
            constant[card] = gain * disc
            continue
        lineup = best_lineup(model, state.player_ids, gw)
        weakest = {
            pos: min((p.xp.get(gw, 0.0) for p in lineup.starters if p.position == pos), default=0.0)
            for pos in LINEUP_COMPOSITION
        }
        day = _gw_day(model, gw)
        values = {}
        # Bara spelare som redan finns i truppen: reservvärdet ska skydda mot att sälja en
        # behörig spelare inför ett kort, inte belöna köp för ett kort långt fram (det bygger
        # på dagens xP för veckor långt bort och är för osäkert att handla på).
        for pid in state.player_ids:
            p = players.get(pid)
            if p is None or not _eligible(card, p, day):
                continue
            xp = p.xp.get(gw, 0.0)
            r = xp if xp >= weakest[p.position] else max(0.0, 2 * xp - weakest[p.position])
            if r > 0:
                values[pid] = r * disc
        per_player[card] = values
    return per_player, constant, best_week


def _off(y: Any) -> bool:
    """Kortet är låst till att inte spelas (konstant 0 i stället för variabel)."""
    return isinstance(y, (int, float)) and y == 0


def _add_cards(
    prob: pulp.LpProblem,
    model: Model,
    state: TeamState,
    players: dict[str, Player],
    weeks: list[tuple[Any, int, float]],
    s: dict,
    c: dict,
    x_final: Callable[[str], Any],
    blocked: set[Any] = frozenset(),
    schedule: frozenset[tuple[int, str]] | None = None,
) -> tuple[list, CardVars]:
    """Lägger till coachkorten i en MIP och returnerar målfunktionens kortdelar.

    weeks: (veckonyckel som används i s och c, matchvecka, vikt). Kaptensvillkoret läggs
    inte här: anroparen sätter Σ kapten = 1 − CardVars.toppa[nyckel] (ingen kapten med
    Toppa Laget).

    - Högst ett kort per vecka och varje kort en gång (använda kort är uteslutna).
    - Dubblingskort: d ≤ startar, d ≤ kortet spelas, kapten + d ≤ 1 (kort och kapten kan
      inte kombineras). Bonus xP·d. Laguttagningen väljs samtidigt, så det räknas rätt när
      kortet gör att en svagare men behörig spelare startar.
    - Toppa Laget: förstafemman f ≤ startar med rätt sammansättning. Bonus xP·e (e ≤ f,
      e ≤ kortet) och andrafemmans bortfall xP·u (u ≥ startar − f + kortet − 1).
    - Värdet av att spara kortet, se _reserve_values.

    schedule: låst kortschema {(matchvecka, kort)}. Då blir kortvariablerna konstanter och
    lösningen går lika snabbt som utan kort (se _best_with_cards). Utan schema väljer MIP:en
    korten fritt, vilket är exakt men för långsamt för hela poolen.
    """
    cv = CardVars()
    cards = [k for k in MIP_CARDS if k not in state.used_cards]
    if not cards or not weeks:
        return [], cv
    terms = []
    for key, gw, _ in weeks:
        cv.week_of[key] = gw
        for card in cards:
            if schedule is not None:
                cv.y[card, key] = 1 if (gw, card) in schedule and key not in blocked else 0
                continue
            cv.y[card, key] = prob.add_variable(f"y_{card}_{gw}", cat="Binary")
            if key in blocked:
                prob += cv.y[card, key] == 0
        if schedule is None:
            prob += pulp.lpSum(cv.y[card, key] for card in cards) <= 1
    if schedule is None:
        for card in cards:
            prob += pulp.lpSum(cv.y[card, key] for key, _, _ in weeks) <= 1

    for key, gw, weight in weeks:
        day = _gw_day(model, gw)
        for card in cards:
            if card == "toppa_laget" or _off(cv.y[card, key]):
                continue
            d = {}
            for pid, p in players.items():
                xp = p.xp.get(gw, 0.0)
                if xp <= 0 or not _eligible(card, p, day):
                    continue
                d[pid] = prob.add_variable(f"d_{card}_{pid}_{gw}", lowBound=0, upBound=1)
                prob += d[pid] <= s[pid, key]
                prob += d[pid] <= cv.y[card, key]
                prob += c[pid, key] + d[pid] <= 1
                terms.append(weight * xp * d[pid])
            # Skärpning: högst så många dubblas per position som startar där, och bara om
            # kortet spelas. Gäller alltid men gör LP-lösningen mycket bättre.
            for pos, n in LINEUP_COMPOSITION.items():
                in_pos = [pid for pid in d if players[pid].position == pos]
                if in_pos:
                    prob += pulp.lpSum(d[pid] for pid in in_pos) <= n * cv.y[card, key]
        if "toppa_laget" in cards and not _off(cv.y["toppa_laget", key]):
            yt = cv.y["toppa_laget", key]
            cv.toppa[key] = yt
            f, e, u = {}, {}, {}
            for pid, p in players.items():
                xp = p.xp.get(gw, 0.0)
                f[pid] = prob.add_variable(f"f_{pid}_{gw}", lowBound=0, upBound=1)
                prob += f[pid] <= s[pid, key]
                if xp <= 0:
                    continue
                e[pid] = prob.add_variable(f"e_{pid}_{gw}", lowBound=0, upBound=1)
                u[pid] = prob.add_variable(f"u_{pid}_{gw}", lowBound=0, upBound=1)
                prob += e[pid] <= f[pid]
                prob += e[pid] <= yt
                prob += u[pid] <= s[pid, key]
                prob += u[pid] >= s[pid, key] - f[pid] + yt - 1
                terms.append(weight * xp * (e[pid] - u[pid]))
            for pos, n in FIRST_FIVE_COMPOSITION.items():
                in_pos = [pid for pid, p in players.items() if p.position == pos]
                prob += pulp.lpSum(f[pid] for pid in in_pos) == n
                # Skärpning: med kortet dubblas högst förstafemman och hela andrafemman
                # tappar sina poäng. Gäller alltid men gör LP-lösningen mycket bättre.
                prob += pulp.lpSum(e[pid] for pid in in_pos if pid in e) <= n * yt
                second = LINEUP_COMPOSITION[pos] - n
                if second:
                    prob += pulp.lpSum(u[pid] for pid in in_pos if pid in u) >= second * yt

    # Värdet av att spara kortet till efter horisonten
    last_gw = max(gw for _, gw, _ in weeks)
    after = [gw["number"] for gw in model.gameweeks if gw["status"] == "upcoming" and gw["number"] > last_gw]
    per_player, constant, _ = _reserve_values(model, state, players, after, weeks[0][1], cards)
    for card in cards:
        ys = [cv.y[card, key] for key, _, _ in weeks]
        played = sum(ys) if schedule is not None else pulp.lpSum(ys)
        if schedule is not None and played >= 1:
            continue  # kortet spelas inom horisonten, inget att spara
        if card in constant:
            cv.reserve[card] = round(constant[card], 2)
            terms.append(constant[card] * (1 - played))
        elif per_player.get(card):
            values = per_player[card]
            bound = sum(sorted(values.values(), reverse=True)[:15])
            z = prob.add_variable(f"z_{card}", lowBound=0)
            prob += z <= pulp.lpSum(v * x_final(pid) for pid, v in values.items())
            if schedule is None:
                prob += z <= bound * (1 - played)
            else:
                prob += z <= bound
            terms.append(z)
            cv.reserve[card] = round(
                sum(v for pid, v in values.items() if pid in state.player_ids), 2
            )
    return terms, cv


CARD_ROUNDS = 3  # högst så många varv mellan kortschema och trupp


def _schedule_for(
    model: Model,
    state: TeamState,
    squads: dict[int, list[str]],
    horizon: list[int],
    blocked: set[int],
) -> frozenset[tuple[int, str]]:
    """Exakt kortplan (högst ett kort per vecka) för en trupp per vecka, begränsad till
    horisonten. Kort som planen lägger senare hanteras av reservvärdet."""
    from .squad import card_plan

    window = model.horizon(max(CARD_IMPACT_WEEKS, len(horizon)))
    last = squads[max(squads)]
    analysis = card_analysis_for(model, {gw: squads.get(gw, last) for gw in window}, state.used_cards)
    return frozenset(
        (c["gameweek"], c["card"])
        for c in card_plan(analysis, state.used_cards, blocked)
        if c["gameweek"] in horizon and c["card"] in MIP_CARDS
    )


def _best_with_cards(
    solve: Callable[[frozenset[tuple[int, str]] | None], tuple[float, Any] | None],
    squads_of: Callable[[Any], dict[int, list[str]]],
    model: Model,
    state: TeamState,
    horizon: list[int],
    blocked: set[int],
) -> Any:
    """Växlar mellan kortschema och trupp.

    1. Exakt kortplan för nuvarande trupp, och att spara alla kort, prövas med låst schema.
    2. För den bästa lösningens trupp räknas kortplanen om. Ändras den löses MIP:en igen.
    Den bästa lösningen (MIP:ens målfunktion, kort inräknade) behålls. Med låst schema går
    varje lösning lika snabbt som utan kort, medan fritt kortval i MIP:en inte hann lösas
    inom tidsgränsen.
    """
    current = {gw: state.player_ids for gw in horizon}
    queue = [_schedule_for(model, state, current, horizon, blocked), frozenset()]
    tried: dict[frozenset, tuple[float, Any]] = {}
    for _ in range(CARD_ROUNDS):
        for sched in queue:
            if sched not in tried:
                solved = solve(sched)
                if solved is not None:
                    tried[sched] = solved
        if not tried:
            return None
        best = max(tried.values(), key=lambda t: t[0])
        nxt = _schedule_for(model, state, squads_of(best[1]), horizon, blocked)
        if nxt in tried:
            break
        queue = [nxt]
    return max(tried.values(), key=lambda t: t[0])[1]


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
    include_cards: bool = True,
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
    # Fria Byten är veckans coachkort, så inget annat kort kan spelas den veckan
    blocked = {gws[0]} if free_card else set()

    # Utan trupp (lag från grunden) finns inget kortvärde att skydda
    use_cards = include_cards and bool(state.player_ids)

    def solve(schedule: frozenset[tuple[int, str]] | None) -> tuple[float, tuple[set[str], list, dict]] | None:
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
        card_terms, cv = (
            _add_cards(
                prob,
                model,
                state,
                players,
                [(gw, gw, HORIZON_DISCOUNT**i) for i, gw in enumerate(gws)],
                s,
                c,
                lambda pid: x[pid],
                blocked=blocked,
                schedule=schedule,
            )
            if use_cards
            else ([], CardVars())
        )
        prob += pulp.lpSum(objective) + pulp.lpSum(card_terms) - TRANSFER_PENALTY * extra

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
                prob += (
                    pulp.lpSum(s[pid, gw] for pid, p in players.items() if p.position == pos) == LINEUP_COMPOSITION[pos]
                )
            # Ingen kapten den vecka Toppa Laget spelas
            prob += pulp.lpSum(c[pid, gw] for pid in pool) == 1 - cv.toppa.get(gw, 0)
            for pid in pool:
                prob += s[pid, gw] <= x[pid]
                prob += c[pid, gw] <= s[pid, gw]

        stats = prob.solve(pulp.HiGHS(msg=False, timeLimit=SOLVER_TIME_LIMIT))
        # Vid tidsgräns används bästa hittade lösning
        if not stats.has_solution:
            return None
        # Läs ut allt här: variablerna går inte att läsa när prob släppts
        chosen = {pid for pid in pool if x[pid].value() > 0.5}
        return pulp.value(prob.objective), (chosen, cv.schedule(), cv.reserve)

    if use_cards:
        best = _best_with_cards(
            solve, lambda sol: {gw: list(sol[0]) for gw in gws}, model, state, gws, blocked
        )
    else:
        solved = solve(None)
        best = solved[1] if solved else None
    if best is None:
        return None
    chosen, card_schedule, card_reserve = best
    out_ids, in_ids = _pair(model, current - chosen, chosen - current)

    evaluation = evaluate_transfers(model, state, out_ids, in_ids, horizon, free_card)
    return {
        "out": out_ids,
        "in": in_ids,
        **evaluation,
        "card_schedule": card_schedule,
        "card_reserve": card_reserve,
    }


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
    include_cards: bool = True,
) -> list[dict]:
    """Bästa förslag för 1..max_transfers byten (dubbletter tas bort). Med korten påslagna
    rankas förslagen på nettovinst inklusive förändringen i kortplanens värde."""
    gain_key = "net_gain_incl_cards" if include_cards else "net_gain"
    options = []
    seen = set()
    limits = [15] if free_card else range(1, max_transfers + 1)
    for k in limits:
        result = optimize(model, state, horizon, k, free_card, locked, banned, include_cards)
        # Byten utan förväntad vinst (t.ex. två bänkspelare med 0 xP) är bara brus
        if not result or not result["out"] or result[gain_key] <= MIN_GAIN:
            continue
        key = (tuple(sorted(result["out"])), tuple(sorted(result["in"])))
        if key in seen:
            continue
        seen.add(key)
        options.append(result)
    options.sort(key=lambda r: r[gain_key], reverse=True)
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
    include_cards: bool = True,
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

    def solve(schedule: frozenset[tuple[int, str]] | None) -> tuple[float, tuple[list, list, dict]] | None:
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
        card_terms, cv = (
            _add_cards(
                prob,
                model,
                state,
                players,
                [(k, gw, HORIZON_DISCOUNT**k) for k, gw in enumerate(gws)],
                s,
                c,
                lambda pid: x[pid, n_transfer_weeks - 1],
                schedule=schedule,
            )
            if include_cards
            else ([], CardVars())
        )
        prob += (
            pulp.lpSum(objective)
            + pulp.lpSum(card_terms)
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
            # Ingen kapten den vecka Toppa Laget spelas
            prob += pulp.lpSum(c[pid, k] for pid in pool) == 1 - cv.toppa.get(k, 0)
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
        return pulp.value(prob.objective), (squads, moves, {"schedule": cv.schedule(), "reserve": cv.reserve})

    def squads_by_gw(sol: tuple[list, list, dict]) -> dict[int, list[str]]:
        return {gw: sol[0][sq(k)] for k, gw in enumerate(gws)}

    if include_cards:
        best = _best_with_cards(solve, squads_by_gw, model, state, gws, set())
    else:
        solved = solve(None)
        best = solved[1] if solved else None
    if best is None:
        return None
    squads, moves, card_info = best

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
    # Exakt kortplan före och efter, med planens trupp vecka för vecka (därefter sista truppen)
    card_gws = model.horizon(CARD_IMPACT_WEEKS)
    plan_squads = {gw: squads[sq(k)] for k, gw in enumerate(gws)}
    cards = card_impact(
        model,
        state.used_cards,
        same_squad(state.player_ids, card_gws),
        {gw: plan_squads.get(gw, squads[-1]) for gw in card_gws},
    )
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
        "card_schedule": card_info["schedule"],
        "card_reserve": card_info["reserve"],
        "cards": cards,
        "net_gain_incl_cards": round(plan_xp - hold_xp - total_penalty + (cards["change"] if cards else 0.0), 2),
    }
