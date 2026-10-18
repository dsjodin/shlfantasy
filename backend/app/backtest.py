"""Backtest av xP-modellen mot spelade matchveckor.

För varje avslutad matchvecka byggs statistiken upp som den såg ut innan veckan började
(ur poängen per matchvecka och matchresultaten), modellen förutsäger veckan och
förutsägelsen jämförs med utfallet.

Begränsning: Fantasy SHL publicerar inte historiska priser, så dagens pris används.
Priset rör sig högst ±0,1 Mkr per match, så felet är litet men gör priset något
"klokare" i efterhand än det var.

Kör: python -m app.backtest [--tune]
"""

from __future__ import annotations

import argparse
import itertools
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .datastore import Snapshot
from .model import assign_gameweek
from .projection import DEFAULT_PARAMS, Params, expected_per_game, game_multiplier, price_priors, team_strength
from .rules import LINEUP_COMPOSITION, POSITIONS

FORM_TEAM_GAMES = 5


@dataclass
class Row:
    pid: str
    position: str
    club: str
    price: float
    games_played: int
    ppg: float
    form: float
    team_games: int
    fixtures: list[tuple[str, bool]]  # (motståndare, hemma) veckan som förutsägs
    actual: int


@dataclass
class Week:
    number: int
    rows: list[Row]
    played_before: list[dict[str, Any]]


def build_weeks(snap: Snapshot, min_week: int = 2) -> list[Week]:
    gameweeks = sorted(snap.gameweeks, key=lambda g: g["number"])
    games = [{**g, "gameweek": assign_gameweek(g["date"], gameweeks)} for g in snap.games if g["played"]]

    team_games: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for g in games:
        if g["gameweek"]:
            team_games[g["home"]][g["gameweek"]] += 1
            team_games[g["away"]][g["gameweek"]] += 1

    history: dict[str, dict[int, dict[str, int]]] = defaultdict(dict)
    for key, rows in snap.gameweek_points.items():
        for pid, row in rows.items():
            history[pid][int(key)] = row

    weeks = []
    completed = [g["number"] for g in gameweeks if g["status"] == "completed" and str(g["number"]) in snap.gameweek_points]
    for wk in completed:
        if wk < min_week:
            continue
        actual_week = snap.gameweek_points[str(wk)]
        rows = []
        for p in snap.players:
            if p["position"] not in POSITIONS or p["id"] not in actual_week:
                continue
            club = p["club"]
            past = {w: r for w, r in history[p["id"]].items() if w < wk}
            gp = sum(r["games"] for r in past.values())
            pts = sum(r["points"] for r in past.values())
            # Form: poäng per lagmatch över (ungefär) de fem senaste lagmatcherna
            form_pts, form_games = 0, 0
            for w in range(wk - 1, 0, -1):
                if form_games >= FORM_TEAM_GAMES:
                    break
                form_games += team_games[club].get(w, 0)
                form_pts += past.get(w, {}).get("points", 0)
            fixtures = [
                (g["away"], True) if g["home"] == club else (g["home"], False)
                for g in games
                if g["gameweek"] == wk and club in (g["home"], g["away"])
            ]
            rows.append(
                Row(
                    pid=p["id"],
                    position=p["position"],
                    club=club,
                    price=p["price"],
                    games_played=gp,
                    ppg=pts / gp if gp else 0.0,
                    form=form_pts / form_games if form_games else 0.0,
                    team_games=sum(n for w, n in team_games[club].items() if w < wk),
                    fixtures=fixtures,
                    actual=actual_week[p["id"]]["points"],
                )
            )
        weeks.append(Week(wk, rows, [g for g in games if g["gameweek"] and g["gameweek"] < wk]))
    return weeks


def predict(week: Week, params: Params) -> list[tuple[Row, float]]:
    priors = price_priors([asdict(r) for r in week.rows], POSITIONS)
    strength = team_strength(week.played_before, params.team_prior_games)
    out = []
    for r in week.rows:
        per_game, _ = expected_per_game(
            price=r.price,
            games_played=r.games_played,
            ppg=r.ppg,
            form=r.form,
            team_games=r.team_games,
            prior=priors[r.position],
            params=params,
        )
        mult = sum(game_multiplier(r.position, opp, home, strength, params) for opp, home in r.fixtures)
        out.append((r, per_game * mult))
    return out


def _lineup_actual(preds: list[tuple[Row, float]], key) -> int:
    total = 0
    for pos, n in LINEUP_COMPOSITION.items():
        ranked = sorted((p for p in preds if p[0].position == pos), key=key, reverse=True)
        total += sum(r.actual for r, _ in ranked[:n])
    return total


def evaluate(weeks: list[Week], params: Params) -> dict[str, Any]:
    errors, pairs = [], []
    by_pos: dict[str, list[float]] = defaultdict(list)
    efficiency = []
    for week in weeks:
        preds = predict(week, params)
        for r, xp in preds:
            errors.append(abs(xp - r.actual))
            by_pos[r.position].append(abs(xp - r.actual))
            pairs.append((xp, r.actual))
        best = _lineup_actual(preds, key=lambda p: p[0].actual)
        chosen = _lineup_actual(preds, key=lambda p: p[1])
        if best > 0:
            efficiency.append(chosen / best)
    return {
        "mae": round(sum(errors) / len(errors), 3) if errors else None,
        "correlation": round(_pearson(pairs), 3) if pairs else None,
        "lineup_efficiency": round(sum(efficiency) / len(efficiency), 3) if efficiency else None,
        "mae_by_position": {pos: round(sum(v) / len(v), 3) for pos, v in by_pos.items()},
        "samples": len(errors),
    }


def _pearson(pairs: list[tuple[float, float]]) -> float:
    n = len(pairs)
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
    return sxy / (sx * sy) if sx and sy else 0.0


BASELINES = {
    "price_only": ("Bara pris och speltid", Params(prior_strength=1e6, form_weight=0.0)),
    "season_avg": ("Säsongssnitt (poäng/match)", Params(prior_strength=1e-6, form_weight=0.0)),
    "form_only": ("Bara form", Params(prior_strength=1e-6, form_weight=1.0)),
}


def report(snap: Snapshot, params: Params = DEFAULT_PARAMS) -> dict[str, Any]:
    weeks = build_weeks(snap)
    if not weeks:
        return {"weeks": [], "models": []}
    models = [{"key": key, "name": name, **evaluate(weeks, p)} for key, (name, p) in BASELINES.items()]
    no_opp = replace(params, opponent_weight=0.0, gk_opponent_weight=0.0, home_advantage=0.0)
    models.append({"key": "basic", "name": "Modellen utan motstånd/hemmaplan", **evaluate(weeks, no_opp)})
    models.append({"key": "current", "name": "Modellen som används", **evaluate(weeks, params)})
    return {
        "weeks": [w.number for w in weeks],
        "models": models,
        "params": asdict(params),
    }


def tune(snap: Snapshot) -> tuple[Params, dict[str, Any]]:
    """Grovt rutnät: välj parametrar med lägst medelfel. Medvetet grovt för att inte
    överanpassa till ett fåtal veckor."""
    weeks = build_weeks(snap)
    grid = itertools.product(
        (2.0, 4.0, 8.0),  # prior_strength
        (0.0, 0.2, 0.35, 0.5),  # form_weight
        (0.0, 0.25, 0.5, 0.75),  # opponent_weight
        (0.0, 0.25, 0.5, 0.75),  # gk_opponent_weight
        (0.0, 0.03, 0.06),  # home_advantage
    )
    best: tuple[float, Params, dict[str, Any]] | None = None
    for ps, fw, ow, gw, ha in grid:
        params = Params(prior_strength=ps, form_weight=fw, opponent_weight=ow, gk_opponent_weight=gw, home_advantage=ha)
        result = evaluate(weeks, params)
        if best is None or result["mae"] < best[0]:
            best = (result["mae"], params, result)
    assert best is not None
    return best[1], best[2]


def main() -> None:
    from .config import get_settings
    from .datastore import DataStore

    parser = argparse.ArgumentParser(description="Backtest av xP-modellen")
    parser.add_argument("--tune", action="store_true", help="Sök bästa parametrar i ett grovt rutnät")
    args = parser.parse_args()
    snap = DataStore(Path(get_settings().data_dir)).snapshot
    result = report(snap)
    print(f"Testveckor: {result['weeks']}")
    print(f"{'Modell':40} {'Medelfel':>9} {'Korr.':>6} {'Elva':>6}")
    for m in result["models"]:
        print(f"{m['name']:40} {m['mae']:>9.2f} {m['correlation']:>6.2f} {m['lineup_efficiency']:>6.0%}")
    if args.tune:
        params, res = tune(snap)
        print(f"\nBästa parametrar: {params}")
        print(f"  medelfel {res['mae']:.3f}, korrelation {res['correlation']:.3f}, elva {res['lineup_efficiency']:.0%}")


if __name__ == "__main__":
    main()
