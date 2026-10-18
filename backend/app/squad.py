"""Regelkontroll, laguttagning, bytesanalys och coachkort."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from .model import Model, Player
from .rules import (
    BENCH_WEIGHT,
    COACH_CARDS,
    FIRST_FIVE_COMPOSITION,
    JUNIOR_MAX_AGE,
    LINEUP_COMPOSITION,
    MAX_FREE_TRANSFERS,
    MAX_PER_CLUB,
    POSITION_NAMES,
    POSITIONS,
    SQUAD_COMPOSITION,
    TRANSFER_PENALTY,
    VETERAN_MIN_AGE,
)

HORIZON_DISCOUNT = 0.9  # framtida veckor väger lite mindre (osäkrare)


@dataclass
class TeamState:
    player_ids: list[str] = field(default_factory=list)
    bank: float = 0.0
    free_transfers: int = 1
    used_cards: list[str] = field(default_factory=list)


@dataclass
class Issue:
    level: str  # "error" | "warning"
    message: str


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def validate_squad(model: Model, ids: list[str], bank: float) -> list[Issue]:
    issues: list[Issue] = []
    unknown = [pid for pid in ids if pid not in model.players]
    for pid in unknown:
        issues.append(Issue("error", f"Okänd spelare med id {pid}."))
    dupes = [pid for pid, n in Counter(ids).items() if n > 1]
    for pid in dupes:
        name = model.players[pid].name if pid in model.players else pid
        issues.append(Issue("error", f"{name} finns med flera gånger."))

    players = [model.players[pid] for pid in dict.fromkeys(ids) if pid in model.players]
    pos_count = Counter(p.position for p in players)
    for pos in POSITIONS:
        have, need = pos_count.get(pos, 0), SQUAD_COMPOSITION[pos]
        if have > need:
            issues.append(Issue("error", f"För många {POSITION_NAMES[pos].lower()}ar: {have} av max {need}."))
        elif have < need:
            issues.append(Issue("error", f"{POSITION_NAMES[pos]}: {have} av {need} valda."))

    for club, n in Counter(p.club for p in players).items():
        if n > MAX_PER_CLUB:
            issues.append(Issue("error", f"{n} spelare från {club} (max {MAX_PER_CLUB})."))

    if bank < -1e-9:
        issues.append(Issue("error", f"Budgeten överskrids med {abs(bank):.1f} Mkr."))

    next_gw = model.next_gameweek
    for p in players:
        if p.status == "injured":
            issues.append(Issue("warning", f"{p.name} är skadad."))
        elif p.status == "unavailable":
            issues.append(Issue("warning", f"{p.name} missade senaste matchen (otillgänglig)."))
        elif next_gw and model.games_in(p.club, next_gw) == 0:
            issues.append(Issue("warning", f"{p.name} ({p.club}) spelar inga matcher vecka {next_gw}."))
    return issues


def is_valid(issues: list[Issue]) -> bool:
    return not any(i.level == "error" for i in issues)


# ---------------------------------------------------------------- laguttagning


@dataclass
class Lineup:
    gameweek: int
    starters: list[Player]
    bench: list[Player]
    first_five: list[Player]
    captain: Player | None
    vice_captain: Player | None
    expected_points: float  # inkl. kaptensbonus

    def to_dict(self) -> dict:
        return {
            "gameweek": self.gameweek,
            "starters": [p.id for p in self.starters],
            "bench": [p.id for p in self.bench],
            "first_five": [p.id for p in self.first_five],
            "second_five": [p.id for p in self.starters if p not in self.first_five],
            "captain": self.captain.id if self.captain else None,
            "vice_captain": self.vice_captain.id if self.vice_captain else None,
            "expected_points": _r(self.expected_points),
        }


def _top_by_position(
    players: list[Player], composition: dict[str, int], score: Callable[[Player], float]
) -> list[Player]:
    chosen = []
    for pos, n in composition.items():
        candidates = sorted((p for p in players if p.position == pos), key=score, reverse=True)
        chosen.extend(candidates[:n])
    return chosen


def best_lineup(model: Model, ids: list[str], gameweek: int) -> Lineup:
    players = [model.players[pid] for pid in ids if pid in model.players]

    def xp(p: Player) -> float:
        return p.xp.get(gameweek, 0.0)

    starters = _top_by_position(players, LINEUP_COMPOSITION, xp)
    bench = [p for p in players if p not in starters]
    first_five = _top_by_position(starters, FIRST_FIVE_COMPOSITION, xp)
    ranked = sorted(starters, key=xp, reverse=True)
    captain = ranked[0] if ranked else None
    vice = ranked[1] if len(ranked) > 1 else None
    total = sum(xp(p) for p in starters) + (xp(captain) if captain else 0)
    return Lineup(gameweek, starters, bench, first_five, captain, vice, total)


def squad_value(model: Model, ids: list[str], gameweeks: list[int]) -> float:
    """Förväntade poäng för truppen över flera veckor med optimal laguttagning."""
    total = 0.0
    for i, gw in enumerate(gameweeks):
        lineup = best_lineup(model, ids, gw)
        bench_xp = sum(p.xp.get(gw, 0.0) for p in lineup.bench)
        total += (lineup.expected_points + BENCH_WEIGHT * bench_xp) * HORIZON_DISCOUNT**i
    return total


# ---------------------------------------------------------------- byten


def apply_transfers(ids: list[str], out_ids: list[str], in_ids: list[str]) -> list[str]:
    out = set(out_ids)
    return [pid for pid in ids if pid not in out] + list(in_ids)


def transfer_penalty(n_transfers: int, free_transfers: int, free_card: bool = False) -> int:
    if free_card:
        return 0
    free = max(0, min(free_transfers, MAX_FREE_TRANSFERS))
    return max(0, n_transfers - free) * TRANSFER_PENALTY


def evaluate_transfers(
    model: Model,
    state: TeamState,
    out_ids: list[str],
    in_ids: list[str],
    horizon: int = 3,
    free_card: bool = False,
) -> dict:
    issues: list[Issue] = []
    if state.player_ids and len(out_ids) != len(in_ids):
        issues.append(Issue("error", f"{len(out_ids)} spelare ut men {len(in_ids)} in – antalet måste vara lika."))
    for pid in out_ids:
        if pid not in state.player_ids:
            issues.append(Issue("error", f"{_name(model, pid)} finns inte i ditt lag."))
    for pid in in_ids:
        if pid in state.player_ids and pid not in out_ids:
            issues.append(Issue("error", f"{_name(model, pid)} finns redan i ditt lag."))

    for o, i in zip(out_ids, in_ids):
        po, pi = model.players.get(o), model.players.get(i)
        if po and pi and po.position != pi.position:
            issues.append(
                Issue("warning", f"{po.name} ({po.position}) ersätts av {pi.name} ({pi.position}) – kontrollera positionerna.")
            )

    price = lambda pid: model.players[pid].price if pid in model.players else 0.0  # noqa: E731
    sold = sum(price(pid) for pid in out_ids)
    bought = sum(price(pid) for pid in in_ids)
    bank_after = state.bank + sold - bought
    new_ids = apply_transfers(state.player_ids, out_ids, in_ids)
    issues.extend(validate_squad(model, new_ids, bank_after))

    gws = model.horizon(horizon)
    next_gw = gws[:1]
    before_next = squad_value(model, state.player_ids, next_gw)
    after_next = squad_value(model, new_ids, next_gw)
    before = squad_value(model, state.player_ids, gws)
    after = squad_value(model, new_ids, gws)
    penalty = transfer_penalty(len(out_ids), state.free_transfers, free_card)

    per_week = [
        {
            "gameweek": gw,
            "before": _r(best_lineup(model, state.player_ids, gw).expected_points),
            "after": _r(best_lineup(model, new_ids, gw).expected_points),
        }
        for gw in gws
    ]
    return {
        "valid": is_valid(issues),
        "issues": [i.__dict__ for i in issues],
        "new_player_ids": new_ids,
        "sold_value": _r(sold),
        "bought_value": _r(bought),
        "bank_before": _r(state.bank),
        "bank_after": _r(bank_after),
        "transfers": len(out_ids),
        "free_transfers": state.free_transfers,
        "penalty": penalty,
        "gameweeks": gws,
        "xp_next_before": _r(before_next),
        "xp_next_after": _r(after_next),
        "xp_horizon_before": _r(before),
        "xp_horizon_after": _r(after),
        "xp_gain_horizon": _r(after - before),
        "net_gain": _r(after - before - penalty),
        "per_week": per_week,
    }


def alternatives(
    model: Model,
    state: TeamState,
    out_id: str,
    horizon: int = 3,
    limit: int = 10,
    max_price: float | None = None,
) -> list[dict]:
    """Bästa möjliga ersättare för en spelare, rangordnade efter förväntad vinst."""
    out = model.players[out_id]
    gws = model.horizon(horizon)
    base = squad_value(model, state.player_ids, gws)
    budget = state.bank + out.price
    if max_price is not None:
        budget = min(budget, max_price)
    remaining = [pid for pid in state.player_ids if pid != out_id]
    club_counts = Counter(model.players[pid].club for pid in remaining if pid in model.players)

    results = []
    for cand in model.players.values():
        if cand.position != out.position or cand.id in state.player_ids:
            continue
        if cand.price > budget + 1e-9 or club_counts.get(cand.club, 0) >= MAX_PER_CLUB:
            continue
        value = squad_value(model, remaining + [cand.id], gws)
        results.append(
            {
                "player_id": cand.id,
                "xp_gain": _r(value - base),
                "xp_horizon": _r(cand.xp_over(gws)),
                "bank_after": _r(state.bank + out.price - cand.price),
            }
        )
    results.sort(key=lambda r: r["xp_gain"], reverse=True)
    return results[:limit]


# ---------------------------------------------------------------- coachkort


def _card_total(players: list[Player], gw: int, doubled: Callable[[Player], bool]) -> float:
    """Poäng med ett kort där vissa spelande spelare får dubbelt. Kaptenen läggs på
    bästa spelare som inte redan dubblas (kort och kapten kan inte kombineras)."""

    def xp(p: Player) -> float:
        return p.xp.get(gw, 0.0)

    starters = _top_by_position(players, LINEUP_COMPOSITION, lambda p: xp(p) * (2 if doubled(p) else 1))
    total = sum(xp(p) * (2 if doubled(p) else 1) for p in starters)
    captain_pool = [xp(p) for p in starters if not doubled(p)]
    return total + (max(captain_pool) if captain_pool else 0.0)


def card_analysis(model: Model, state: TeamState, weeks: int = 6) -> list[dict]:
    players = [model.players[pid] for pid in state.player_ids if pid in model.players]
    result = []
    for gw in model.horizon(weeks):
        info = model.gameweek(gw)
        day = date.fromisoformat(info["start"]) if info else date.today()
        normal = best_lineup(model, state.player_ids, gw)

        def xp(p: Player) -> float:
            return p.xp.get(gw, 0.0)

        first_five = _top_by_position(players, FIRST_FIVE_COMPOSITION, xp)
        gains = {
            "toppa_laget": 2 * sum(xp(p) for p in first_five) - normal.expected_points,
            "anfall": _card_total(players, gw, lambda p: p.position == "F") - normal.expected_points,
            "forsvar": _card_total(players, gw, lambda p: p.position == "D") - normal.expected_points,
        }
        juniors = [p for p in players if (a := p.age_on(day)) is not None and a <= JUNIOR_MAX_AGE]
        veterans = [p for p in players if (a := p.age_on(day)) is not None and a >= VETERAN_MIN_AGE]
        has_ages = any(p.birth_date for p in players)
        gains["juniorer"] = (
            _card_total(players, gw, lambda p: p in juniors) - normal.expected_points if has_ages else None
        )
        gains["veteraner"] = (
            _card_total(players, gw, lambda p: p in veterans) - normal.expected_points if has_ages else None
        )
        result.append(
            {
                "gameweek": gw,
                "start": info["start"] if info else None,
                "end": info["end"] if info else None,
                "expected_points": _r(normal.expected_points),
                "squad_games": sum(model.games_in(p.club, gw) for p in normal.starters),
                "cards": {
                    key: {
                        "name": COACH_CARDS[key],
                        "gain": None if g is None else _r(g),
                        "used": key in state.used_cards,
                    }
                    for key, g in gains.items()
                },
                "juniors": [p.id for p in juniors],
                "veterans": [p.id for p in veterans],
            }
        )
    return result


def _name(model: Model, pid: str) -> str:
    return model.players[pid].name if pid in model.players else pid
