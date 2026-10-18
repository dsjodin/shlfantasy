"""Backtest av xP-modellen mot spelade matchveckor.

För varje avslutad matchvecka byggs statistiken upp som den såg ut innan veckan började
(ur poängen per matchvecka och matchresultaten), modellen förutsäger veckan och
förutsägelsen jämförs med utfallet.

Begränsning: Fantasy SHL publicerar inte historiska priser. För veckor där prognosarkivet
(archive.py) har sparat priserna vid deadline används de; annars dagens pris, som redan
påverkats av de testade veckorna och därför gör priset något "klokare" i efterhand.

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

from .archive import PredictionArchive
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
    archived_prices: bool = False


def build_weeks(snap: Snapshot, archive: PredictionArchive | None = None, min_week: int = 2) -> list[Week]:
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
        saved = (archive.load(wk) if archive else None) or {}
        saved_players = saved.get("players", {})
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
                    price=saved_players.get(p["id"], {}).get("price", p["price"]),
                    games_played=gp,
                    ppg=pts / gp if gp else 0.0,
                    form=form_pts / form_games if form_games else 0.0,
                    team_games=sum(n for w, n in team_games[club].items() if w < wk),
                    fixtures=fixtures,
                    actual=actual_week[p["id"]]["points"],
                )
            )
        played_before = [g for g in games if g["gameweek"] and g["gameweek"] < wk]
        weeks.append(Week(wk, rows, played_before, archived_prices=bool(saved_players)))
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


Prediction = tuple[str, float, int]  # (position, xP, faktiska poäng)


def _lineup_actual(preds: list[Prediction], by_prediction: bool) -> int:
    total = 0
    for pos, n in LINEUP_COMPOSITION.items():
        ranked = sorted((p for p in preds if p[0] == pos), key=lambda p: p[1] if by_prediction else p[2], reverse=True)
        total += sum(actual for _, _, actual in ranked[:n])
    return total


def score(weeks_of_predictions: list[list[Prediction]]) -> dict[str, Any]:
    errors, pairs = [], []
    by_pos: dict[str, list[float]] = defaultdict(list)
    efficiency = []
    for preds in weeks_of_predictions:
        for pos, xp, actual in preds:
            errors.append(abs(xp - actual))
            by_pos[pos].append(abs(xp - actual))
            pairs.append((xp, actual))
        best = _lineup_actual(preds, by_prediction=False)
        if best > 0:
            efficiency.append(_lineup_actual(preds, by_prediction=True) / best)
    return {
        "mae": round(sum(errors) / len(errors), 3) if errors else None,
        "correlation": round(_pearson(pairs), 3) if pairs else None,
        "lineup_efficiency": round(sum(efficiency) / len(efficiency), 3) if efficiency else None,
        "mae_by_position": {pos: round(sum(v) / len(v), 3) for pos, v in by_pos.items()},
        "samples": len(errors),
    }


def evaluate(weeks: list[Week], params: Params) -> dict[str, Any]:
    return score([[(r.position, xp, r.actual) for r, xp in predict(w, params)] for w in weeks])


def evaluate_archived(snap: Snapshot, archive: PredictionArchive) -> tuple[list[int], dict[str, Any] | None]:
    """Exakt utvärdering: prognosen som sparades vid deadline mot utfallet."""
    completed = {str(g["number"]) for g in snap.gameweeks if g["status"] == "completed"}
    weeks, preds = [], []
    for gw in archive.weeks():
        actual = snap.gameweek_points.get(str(gw))
        saved = archive.load(gw)
        if str(gw) not in completed or not actual or not saved:
            continue
        weeks.append(gw)
        preds.append(
            [(row["position"], row["xp"], actual[pid]["points"]) for pid, row in saved["players"].items() if pid in actual]
        )
    return weeks, (score(preds) if preds else None)


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


def report(
    snap: Snapshot,
    params: Params = DEFAULT_PARAMS,
    archive: PredictionArchive | None = None,
) -> dict[str, Any]:
    weeks = build_weeks(snap, archive)
    if not weeks:
        return {"weeks": [], "models": []}
    models = [{"key": key, "name": name, **evaluate(weeks, p)} for key, (name, p) in BASELINES.items()]
    no_opp = replace(params, opponent_weight=0.0, gk_opponent_weight=0.0, home_advantage=0.0)
    models.append({"key": "basic", "name": "Modellen utan motstånd/hemmaplan", **evaluate(weeks, no_opp)})
    models.append({"key": "current", "name": "Modellen som används", **evaluate(weeks, params)})
    result: dict[str, Any] = {
        "weeks": [w.number for w in weeks],
        "archived_price_weeks": [w.number for w in weeks if w.archived_prices],
        "models": models,
        "params": asdict(params),
    }
    if archive:
        archived_weeks, archived = evaluate_archived(snap, archive)
        if archived:
            result["archived"] = {"weeks": archived_weeks, "name": "Sparade prognoser vid deadline", **archived}
    return result


PRIOR_GRID = (2.0, 4.0, 6.0)
PRIOR_GRID_WITH_ARCHIVED_PRICES = (2.0, 4.0, 6.0, 8.0, 12.0)


def grid_search(weeks: list[Week], prior_grid: tuple[float, ...] = PRIOR_GRID) -> tuple[Params, dict[str, Any]]:
    """Grovt rutnät: välj parametrar med lägst medelfel. Medvetet grovt för att inte
    överanpassa till ett fåtal veckor."""
    grid = itertools.product(
        prior_grid,
        (0.0, 0.1, 0.2, 0.35, 0.5),  # form_weight
        (0.0, 0.25, 0.5, 0.75),  # opponent_weight
        (0.0, 0.25, 0.5),  # gk_opponent_weight
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
    data_dir = Path(get_settings().data_dir)
    snap = DataStore(data_dir).snapshot
    archive = PredictionArchive(data_dir)
    result = report(snap, archive=archive)
    print(f"Testveckor: {result['weeks']}")
    print(f"{'Modell':40} {'Medelfel':>9} {'Korr.':>6} {'Elva':>6}")
    for m in result["models"]:
        print(f"{m['name']:40} {m['mae']:>9.2f} {m['correlation']:>6.2f} {m['lineup_efficiency']:>6.0%}")
    if "archived" in result:
        a = result["archived"]
        print(f"{a['name'] + ' ' + str(a['weeks']):40} {a['mae']:>9.2f} {a['correlation']:>6.2f} {a['lineup_efficiency']:>6.0%}")
    if args.tune:
        params, res = grid_search(build_weeks(snap, archive), PRIOR_GRID_WITH_ARCHIVED_PRICES)
        print(f"\nBästa parametrar: {params}")
        print(f"  medelfel {res['mae']:.3f}, korrelation {res['correlation']:.3f}, elva {res['lineup_efficiency']:.0%}")


if __name__ == "__main__":
    main()
