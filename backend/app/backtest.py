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

from . import exceptions as exc
from .archive import PredictionArchive
from .datastore import Snapshot
from .model import assign_gameweek
from .projection import (
    DEFAULT_PARAMS,
    POINTS_TREND_WEIGHT_OPTION,
    Params,
    categories_complete,
    category_means,
    category_ppg,
    expected_per_game,
    game_multiplier,
    price_priors,
    swept_clubs,
    team_strength,
)
from .rules import LINEUP_COMPOSITION, POSITIONS
from .trend import WeekStat, plus_minus_per_game, recent_play_rate, spike_per_game, toi_by_week, toi_ratio
from .trend import compute as compute_trend

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
    weeks: list[WeekStat]  # spelarens veckor före den som förutsägs
    cats: dict[str, int]  # poäng per kategori före veckan


@dataclass
class Week:
    number: int
    rows: list[Row]
    played_before: list[dict[str, Any]]
    archived_prices: bool = False


def build_weeks(
    snap: Snapshot,
    archive: PredictionArchive | None = None,
    min_week: int = 2,
    absences: list[exc.Absence] | None = None,
) -> list[Week]:
    gameweeks = sorted(snap.gameweeks, key=lambda g: g["number"])
    games = [{**g, "gameweek": assign_gameweek(g["date"], gameweeks)} for g in snap.games if g["played"]]
    club_games: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in games:
        club_games[g["home"]].append(g)
        club_games[g["away"]].append(g)
    absences_by_player = exc.by_player(absences or [])
    toi = toi_by_week(snap.boxscores, {g["id"]: g["gameweek"] for g in games if g["gameweek"]})

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
            player_weeks = [
                WeekStat(
                    w,
                    past.get(w, {}).get("games", 0),
                    past.get(w, {}).get("points", 0),
                    n,
                    past.get(w, {}).get("pm", 0),
                    *toi.get(p["id"], {}).get(w, (0, 0)),
                )
                for w, n in sorted(team_games[club].items())
                if w < wk
            ]
            # Samma frånvaroundantag som i modellen (exceptions.py)
            player_weeks, _ = exc.adjust_weeks(
                player_weeks, exc.excused_team_games(absences_by_player.get(p["id"], []), club_games[club])
            )
            rows.append(
                Row(
                    pid=p["id"],
                    position=p["position"],
                    club=club,
                    price=saved_players.get(p["id"], {}).get("price", p["price"]),
                    games_played=gp,
                    ppg=pts / gp if gp else 0.0,
                    form=form_pts / form_games if form_games else 0.0,
                    team_games=sum(w.team_games for w in player_weeks),
                    fixtures=fixtures,
                    actual=actual_week[p["id"]]["points"],
                    cats=_sum_cats(past.values()),
                    weeks=player_weeks,
                )
            )
        played_before = [g for g in games if g["gameweek"] and g["gameweek"] < wk]
        weeks.append(Week(wk, rows, played_before, archived_prices=bool(saved_players)))
    return weeks


def _sum_cats(rows) -> dict[str, int]:
    total: dict[str, int] = defaultdict(int)
    for r in rows:
        for c, v in r.get("cats", {}).items():
            total[c] += v
    return dict(total)


def predict(week: Week, params: Params) -> list[tuple[Row, float]]:
    priors = price_priors([asdict(r) for r in week.rows], POSITIONS)
    complete = {r.pid for r in week.rows if categories_complete(r.cats, round(r.ppg * r.games_played))}
    means = category_means((r.position, r.cats, r.games_played) for r in week.rows if r.pid in complete)
    strength = team_strength(week.played_before, params.team_prior_games, params.team_half_life)
    hot = swept_clubs(week.played_before, week.number - 1) if params.hot_week_penalty else set()
    out = []
    for r in week.rows:
        trend = compute_trend(r.weeks, params.play_half_life) if params.points_trend_weight else None
        use_categories = (
            params.category_model
            and r.position != "GK"
            and r.games_played
            and r.position in means
            and r.pid in complete
        )
        per_game, play_rate = expected_per_game(
            price=r.price,
            games_played=r.games_played,
            ppg=category_ppg(r.cats, r.games_played, means[r.position], params) if use_categories else r.ppg,
            form=r.form,
            team_games=r.team_games,
            prior=priors[r.position],
            params=params,
            recent_play=recent_play_rate(r.weeks, params.play_half_life),
            ppg_delta=trend.ppg_delta if trend else 0.0,
            pm_per_game=plus_minus_per_game(r.weeks) if r.position != "GK" else 0.0,
            toi_ratio=toi_ratio(r.weeks) if r.position != "GK" else None,
            spike=spike_per_game(r.weeks) if r.position != "GK" else 0.0,
        )
        mult = sum(game_multiplier(r.position, opp, home, strength, params) for opp, home in r.fixtures)
        xp = per_game * mult
        if r.club in hot:
            xp = max(0.0, xp - params.hot_week_penalty * len(r.fixtures) * play_rate)
        out.append((r, xp))
    return out


Prediction = tuple[str, float, int]  # (position, xP, faktiska poäng)


def _lineup_actual(preds: list[Prediction], by_prediction: bool) -> int:
    total = 0
    for pos, n in LINEUP_COMPOSITION.items():
        ranked = sorted((p for p in preds if p[0] == pos), key=lambda p: p[1] if by_prediction else p[2], reverse=True)
        total += sum(actual for _, _, actual in ranked[:n])
    return total


BUY_TOP_N = 5  # köpträff: modellens N bästa per position och vecka


def _ranks(values: list[float]) -> list[float]:
    """Rang med medelrang vid lika värden."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def _spearman(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 3:
        return 0.0
    rx = _ranks([x for x, _ in pairs])
    ry = _ranks([y for _, y in pairs])
    return _pearson(list(zip(rx, ry)))


def _buy_hit(preds: list[Prediction]) -> list[float]:
    """Per position: faktiska poäng för modellens N bästa som andel av de N faktiskt bästas.
    Mäter hur bra köpen blir, eftersom man köper de spelare modellen rankar högst."""
    out = []
    for pos in LINEUP_COMPOSITION:
        group = [p for p in preds if p[0] == pos]
        best = sum(sorted((a for _, _, a in group), reverse=True)[:BUY_TOP_N])
        if best > 0:
            chosen = sorted(group, key=lambda p: p[1], reverse=True)[:BUY_TOP_N]
            out.append(sum(a for _, _, a in chosen) / best)
    return out


def score(weeks_of_predictions: list[list[Prediction]]) -> dict[str, Any]:
    errors, pairs = [], []
    by_pos: dict[str, list[float]] = defaultdict(list)
    efficiency, rank_corr, buy_hit = [], [], []
    for preds in weeks_of_predictions:
        for pos, xp, actual in preds:
            errors.append(abs(xp - actual))
            by_pos[pos].append(abs(xp - actual))
            pairs.append((xp, actual))
        best = _lineup_actual(preds, by_prediction=False)
        if best > 0:
            efficiency.append(_lineup_actual(preds, by_prediction=True) / best)
        # Rangkorrelation per vecka bland spelare modellen tror spelar (xP > 0)
        playing = [(xp, a) for _, xp, a in preds if xp > 0]
        if len(playing) >= 3:
            rank_corr.append(_spearman(playing))
        buy_hit.extend(_buy_hit(preds))
    mean = lambda v: round(sum(v) / len(v), 3) if v else None  # noqa: E731
    return {
        "mae": round(sum(errors) / len(errors), 3) if errors else None,
        "correlation": round(_pearson(pairs), 3) if pairs else None,
        "rank_correlation": mean(rank_corr),
        "buy_hit": mean(buy_hit),
        "lineup_efficiency": mean(efficiency),
        "mae_by_position": {pos: round(sum(v) / len(v), 3) for pos, v in by_pos.items()},
        "samples": len(errors),
    }


def evaluate(weeks: list[Week], params: Params) -> dict[str, Any]:
    return score([[(r.position, xp, r.actual) for r, xp in predict(w, params)] for w in weeks])


def predictions(week: Week, params: Params) -> list[Prediction]:
    return [(r.position, xp, r.actual) for r, xp in predict(week, params)]


ROLLING_START = 5  # första testveckan i den rullande utvärderingen


def rolling_evaluation(weeks: list[Week], grid: list[Params], start: int = ROLLING_START) -> dict[str, Any]:
    """Utvärdering utanför träningsdatan. För varje testvecka k (från `start`) väljs den
    kandidat i `grid` som hade lägst medelfel på veckorna före k, och den mäts sedan på
    vecka k. Med en enda kandidat blir det en vanlig mätning på samma testveckor, vilket
    gör den till en rättvis jämförelse mot dagens modell."""
    cache: dict[tuple[int, int], list[Prediction]] = {}

    def preds(i: int, week: Week) -> list[Prediction]:
        key = (i, week.number)
        if key not in cache:
            cache[key] = predictions(week, grid[i])
        return cache[key]

    tested, chosen, per_week = [], [], []
    for k, week in enumerate(weeks):
        if week.number < start:
            continue
        train = weeks[:k]
        if len(grid) == 1 or not train:
            best = 0
        else:
            best = min(range(len(grid)), key=lambda i: score([preds(i, w) for w in train])["mae"])
        p = preds(best, week)
        tested.append(p)
        chosen.append(best)
        per_week.append({"week": week.number, **{m: v for m, v in score([p]).items() if m != "mae_by_position"}})
    return {**score(tested), "weeks": [w["week"] for w in per_week], "per_week": per_week, "chosen": chosen}


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
    absences: list[exc.Absence] | None = None,
) -> dict[str, Any]:
    weeks = build_weeks(snap, archive, absences=absences)
    if not weeks:
        return {"weeks": [], "models": []}
    models = [{"key": key, "name": name, **evaluate(weeks, p)} for key, (name, p) in BASELINES.items()]
    no_opp = replace(params, opponent_weight=0.0, gk_opponent_weight=0.0, home_advantage=0.0)
    models.append({"key": "basic", "name": "Modellen utan motstånd/hemmaplan", **evaluate(weeks, no_opp)})
    no_play = replace(params, recent_play_weight=0.0)
    models.append({"key": "no_play_trend", "name": "Modellen utan speltidstrend", **evaluate(weeks, no_play)})
    no_cat = replace(params, category_model=False, pdo_weight=1.0)
    models.append({"key": "no_categories", "name": "Modellen utan kategorivikter (bara PDO)", **evaluate(weeks, no_cat)})
    no_pdo = replace(params, category_model=False, pdo_weight=0.0)
    models.append({"key": "no_pdo", "name": "Modellen utan kategorivikter och PDO", **evaluate(weeks, no_pdo)})
    no_spike = replace(params, spike_weight=0.0)
    models.append({"key": "no_spike", "name": "Modellen utan dämpning av toppvecka", **evaluate(weeks, no_spike)})
    no_hot = replace(params, hot_week_penalty=0.0)
    models.append({"key": "no_hot_week", "name": "Modellen utan avdrag efter het lagvecka", **evaluate(weeks, no_hot)})
    no_toi = replace(params, toi_trend_weight=0.0)
    models.append({"key": "no_toi_trend", "name": "Modellen utan istidstrend", **evaluate(weeks, no_toi)})
    with_points = replace(params, points_trend_weight=POINTS_TREND_WEIGHT_OPTION)
    models.append({"key": "points_trend", "name": "Modellen med poängtrend", **evaluate(weeks, with_points)})
    models.append({"key": "current", "name": "Modellen som används", **evaluate(weeks, params)})
    result: dict[str, Any] = {
        "weeks": [w.number for w in weeks],
        "archived_price_weeks": [w.number for w in weeks if w.archived_prices],
        "models": models,
        "params": asdict(params),
    }
    rolling = rolling_evaluation(weeks, [params])
    if rolling["weeks"]:
        result["rolling"] = {k: rolling[k] for k in ("weeks", "mae", "correlation", "rank_correlation", "buy_hit", "lineup_efficiency")}
    if archive:
        archived_weeks, archived = evaluate_archived(snap, archive)
        if archived:
            result["archived"] = {"weeks": archived_weeks, "name": "Sparade prognoser vid deadline", **archived}
    return result


PRIOR_GRID = (2.0, 4.0, 6.0)
PRIOR_GRID_WITH_ARCHIVED_PRICES = (2.0, 4.0, 6.0, 8.0, 12.0)


def grid_search(
    weeks: list[Week], prior_grid: tuple[float, ...] = PRIOR_GRID, base: Params = DEFAULT_PARAMS
) -> tuple[Params, dict[str, Any]]:
    """Grovt rutnät i två steg: välj parametrar med lägst medelfel. Medvetet grovt för att
    inte överanpassa till ett fåtal veckor.

    Alla kandidater byggs från `base` med replace(), så vikter som inte söks behåller sina
    värden. Annars skulle t.ex. kategorimodellen och istidstrenden tyst stängas av.
    Steg 1 söker grundvikterna, steg 2 trendvikterna med steg 1:s bästa grund. Kategori-
    modellen och poängtrenden söks inte: de är val som backtesten redan har avgjort.
    """
    best: tuple[float, Params, dict[str, Any]] | None = None
    for ps, fw, ow, gw, ha in itertools.product(
        prior_grid,
        (0.0, 0.1, 0.2, 0.35, 0.5),  # form_weight
        (0.0, 0.25, 0.5, 0.75),  # opponent_weight
        (0.0, 0.25, 0.5),  # gk_opponent_weight
        (0.0, 0.03, 0.06),  # home_advantage
    ):
        params = replace(
            base, prior_strength=ps, form_weight=fw, opponent_weight=ow, gk_opponent_weight=gw, home_advantage=ha
        )
        result = evaluate(weeks, params)
        if best is None or result["mae"] < best[0]:
            best = (result["mae"], params, result)
    assert best is not None
    stage1 = best[1]
    for rw, tw, kc in itertools.product(
        (0.5, 1.0),  # recent_play_weight
        (0.5, 1.0),  # toi_trend_weight
        (5.0, 10.0, 20.0),  # scoring_shrink
    ):
        params = replace(stage1, recent_play_weight=rw, toi_trend_weight=tw, scoring_shrink=kc)
        result = evaluate(weeks, params)
        if result["mae"] < best[0]:
            best = (result["mae"], params, result)
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
    absences, _ = exc.load(data_dir)
    result = report(snap, archive=archive, absences=absences)
    print(f"Testveckor: {result['weeks']}")
    print(f"{'Modell':40} {'Medelfel':>9} {'Korr.':>6} {'Rang':>6} {'Köp':>6} {'Elva':>6}")

    def line(name: str, m: dict) -> None:
        print(
            f"{name:40} {m['mae']:>9.2f} {m['correlation']:>6.2f} {m['rank_correlation']:>6.2f} "
            f"{m['buy_hit']:>6.0%} {m['lineup_efficiency']:>6.0%}"
        )

    for m in result["models"]:
        line(m["name"], m)
    if "rolling" in result:
        r = result["rolling"]
        line(f"Rullande, vecka {r['weeks'][0]}–{r['weeks'][-1]} (som används)", r)
    if "archived" in result:
        a = result["archived"]
        line(a["name"] + " " + str(a["weeks"]), a)
    if args.tune:
        params, res = grid_search(build_weeks(snap, archive, absences=absences), PRIOR_GRID_WITH_ARCHIVED_PRICES)
        print(f"\nBästa parametrar: {params}")
        print(f"  medelfel {res['mae']:.3f}, korrelation {res['correlation']:.3f}, elva {res['lineup_efficiency']:.0%}")


if __name__ == "__main__":
    main()
