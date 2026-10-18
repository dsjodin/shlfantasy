"""Poängformeln bakom xP. Ren funktion av indata så att samma kod kan köras både framåt
(prognos) och bakåt (backtest mot spelade matchveckor)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Params:
    prior_strength: float = 4.0  # antal "låtsasmatcher" för pris-priorn
    form_weight: float = 0.35  # hur mycket senaste formen väger
    opponent_weight: float = 0.0  # utespelare: effekt av motståndarens insläppta mål
    gk_opponent_weight: float = 0.0  # målvakter: effekt av motståndarens gjorda mål
    home_advantage: float = 0.0  # +x hemma, −x borta
    team_prior_games: float = 6.0  # krympning av lagstyrka mot ligasnittet


# Valda med backtest mot matchvecka 2–5 säsongen 2026/27 (python -m app.backtest --tune).
# Rutnätet föredrog ännu tyngre pris och ingen form (8 / 0,0), men backtesten använder dagens
# pris som redan påverkats av testveckorna. Därför en försiktigare mellanväg för priset.
# Motstånd och hemmaplan förbättrade i 3 av 4 veckor även i varianter utan pris.
# Motståndseffekten för målvakter gav ingenting och är avstängd.
DEFAULT_PARAMS = Params(
    prior_strength=6.0,
    form_weight=0.1,
    opponent_weight=0.5,
    gk_opponent_weight=0.0,
    home_advantage=0.06,
)


@dataclass(frozen=True)
class TeamStrength:
    goals_for: dict[str, float]  # per match, krympt mot snittet
    goals_against: dict[str, float]
    average: float

    def attack(self, club: str) -> float:
        return self.goals_for.get(club, self.average) / self.average if self.average else 1.0

    def defence_leak(self, club: str) -> float:
        """>1 = släpper in fler mål än snittet."""
        return self.goals_against.get(club, self.average) / self.average if self.average else 1.0


def team_strength(played_games: Iterable[dict[str, Any]], prior_games: float) -> TeamStrength:
    gf: dict[str, float] = {}
    ga: dict[str, float] = {}
    n: dict[str, int] = {}
    total_goals = 0
    total_team_games = 0
    for g in played_games:
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None:
            continue
        for club, scored, conceded in ((g["home"], hs, as_), (g["away"], as_, hs)):
            gf[club] = gf.get(club, 0) + scored
            ga[club] = ga.get(club, 0) + conceded
            n[club] = n.get(club, 0) + 1
        total_goals += hs + as_
        total_team_games += 2
    avg = total_goals / total_team_games if total_team_games else 0.0
    shrink = lambda total, games: (total + prior_games * avg) / (games + prior_games)  # noqa: E731
    return TeamStrength(
        goals_for={c: shrink(gf[c], n[c]) for c in n},
        goals_against={c: shrink(ga[c], n[c]) for c in n},
        average=avg,
    )


def expected_per_game(
    *,
    price: float,
    games_played: int,
    ppg: float,
    form: float,
    team_games: int,
    prior: tuple[float, float],
    params: Params,
) -> tuple[float, float]:
    """Förväntade poäng per lagmatch och speltidsandel."""
    intercept, slope = prior
    prior_ppg = max(intercept + slope * price, 0.5)
    gp = games_played
    quality = (gp * ppg + params.prior_strength * prior_ppg) / (gp + params.prior_strength)
    if team_games == 0:
        return quality, 1.0
    # Lätt krympning så att en enstaka missad match inte slår för hårt
    play_rate = min(1.0, (gp + 0.5) / (team_games + 0.5))
    base = quality * play_rate
    return (1 - params.form_weight) * base + params.form_weight * form, play_rate


def game_multiplier(
    position: str, opponent: str, home: bool, strength: TeamStrength | None, params: Params
) -> float:
    """Justering för en enskild match utifrån motstånd och hemmaplan.

    Utespelarnas poäng drivs av mål, så motståndarens insläppta mål används. Målvakter
    tjänar på motståndare som gör få mål (färre insläppta, fler vinster och nollor).
    Det egna lagets styrka finns redan i spelarens egen poängsnitt och räknas inte igen.
    """
    mult = 1.0
    if strength and strength.average:
        if position == "GK":
            mult += params.gk_opponent_weight * (1 - strength.attack(opponent))
        else:
            mult += params.opponent_weight * (strength.defence_leak(opponent) - 1)
    mult *= 1 + params.home_advantage if home else 1 - params.home_advantage
    return min(max(mult, 0.5), 1.6)


def price_priors(rows: list[dict[str, Any]], positions: Iterable[str]) -> dict[str, tuple[float, float]]:
    """Viktad linjär regression ppg ~ pris per position. Returnerar (intercept, lutning)."""
    priors = {}
    for pos in positions:
        data = [(r["price"], r["ppg"], r["games_played"]) for r in rows if r["position"] == pos and r["games_played"] >= 3]
        w_sum = sum(w for _, _, w in data)
        if len(data) < 5 or w_sum == 0:
            priors[pos] = (sum(d[1] for d in data) / len(data) if data else 2.0, 0.0)
            continue
        mx = sum(x * w for x, _, w in data) / w_sum
        my = sum(y * w for _, y, w in data) / w_sum
        var = sum(w * (x - mx) ** 2 for x, _, w in data)
        slope = sum(w * (x - mx) * (y - my) for x, y, w in data) / var if var else 0.0
        priors[pos] = (my - slope * mx, max(slope, 0.0))
    return priors
