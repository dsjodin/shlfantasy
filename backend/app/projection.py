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
    recent_play_weight: float = 0.0  # 0 = säsongens speltidsandel, 1 = senaste veckornas
    play_half_life: float = 1.5  # veckor, för speltidstrenden
    points_trend_weight: float = 0.0  # hur mycket poängtrenden (senaste veckorna mot säsongen) väger
    pdo_weight: float = 0.0  # andel av plus/minus-poängen som antas vara tur och dras bort (utespelare)
    # Kategorimodellen (utespelare): varje poängkategori krymps mot positionens snitt för sig.
    # Talet är antal "låtsasmatcher" med positionssnittet. Lågt = spelarens egen siffra litas på.
    category_model: bool = False
    stable_shrink: float = 0.5  # istid, tacklingar, blockerade skott, tekningar, skott
    scoring_shrink: float = 10.0  # mål och assist


# Valda med backtest mot matchvecka 2–5 säsongen 2026/27 (python -m app.backtest --tune).
# Rutnätet föredrog ännu tyngre pris och ingen form (8 / 0,0), men backtesten använder dagens
# pris som redan påverkats av testveckorna. Därför en försiktigare mellanväg för priset.
# Motstånd och hemmaplan förbättrade i 3 av 4 veckor även i varianter utan pris.
# Motståndseffekten för målvakter gav ingenting och är avstängd.
# Speltidstrend, poängtrend, PDO-korrigering och kategorimodell testades mot matchvecka 2–9 (se
# trend.py och README). Alla utom poängtrenden förbättrade.
DEFAULT_PARAMS = Params(
    prior_strength=6.0,
    form_weight=0.1,
    opponent_weight=0.5,
    gk_opponent_weight=0.0,
    home_advantage=0.06,
    recent_play_weight=1.0,
    play_half_life=1.0,
    points_trend_weight=0.0,
    # Med kategorimodellen ersätts plus/minus av positionens snitt, så PDO-korrigeringen behövs
    # inte. Utan kategorimodellen var pdo_weight=1,0 bäst.
    pdo_weight=0.0,
    category_model=True,
    stable_shrink=0.5,
    scoring_shrink=10.0,
)

# Poängkategorier för utespelare, grupperade efter hur väl de upprepar sig från vecka till vecka
# (korrelation mellan udda och jämna veckor, matchvecka 1–9 2026/27): istid 0,87, tacklingar och
# blockerade skott runt 0,57, skott 0,46, mål och assist 0,29, utvisningar 0,11, plus/minus 0,05,
# matchavgörande mål 0,04. Den sista gruppen ersätts helt av positionens snitt.
STABLE_CATEGORIES = (
    "time_on_ice_points",
    "hits_points",
    "blocked_shots_points",
    "faceoffs_won_points",
    "shots_on_goal_points",
)
SCORING_CATEGORIES = ("goals_points", "assists_points", "shorthanded_goals_points")
NOISE_CATEGORIES = ("plus_minus_points", "game_winning_goals_points", "penalty_minutes_points", "other_points")
SKATER_CATEGORIES = STABLE_CATEGORIES + SCORING_CATEGORIES + NOISE_CATEGORIES


def category_means(rows: Iterable[tuple[str, dict[str, int], int]]) -> dict[str, dict[str, float]]:
    """Positionens snitt per kategori och spelad match. rows = (position, kategorier, matcher)."""
    totals: dict[str, dict[str, float]] = {}
    games: dict[str, int] = {}
    for pos, cats, gp in rows:
        if pos == "GK" or not gp:
            continue
        t = totals.setdefault(pos, dict.fromkeys(SKATER_CATEGORIES, 0.0))
        for c in SKATER_CATEGORIES:
            t[c] += cats.get(c, 0)
        games[pos] = games.get(pos, 0) + gp
    return {pos: {c: v / games[pos] for c, v in t.items()} for pos, t in totals.items()}


def categories_complete(cats: dict[str, int], total_points: int) -> bool:
    """Kategorimodellen används bara när fördelningen går ihop med totalen. Annars (t.ex. om
    kolumnerna saknas i exporten) skulle spelaren få 0 poäng."""
    return abs(sum(cats.get(c, 0) for c in SKATER_CATEGORIES) - total_points) <= 1


def category_ppg(cats: dict[str, int], games: int, means: dict[str, float], params: Params) -> float:
    """Poäng per match där varje kategori krymps för sig: istid och andra stabila kategorier
    nästan inte alls, mål och assist hårt, och tur-kategorierna ersätts av positionens snitt."""
    total = 0.0
    for group, k in ((STABLE_CATEGORIES, params.stable_shrink), (SCORING_CATEGORIES, params.scoring_shrink)):
        for c in group:
            total += (cats.get(c, 0) + k * means.get(c, 0.0)) / (games + k)
    total += sum(means.get(c, 0.0) for c in NOISE_CATEGORIES)
    return total


# Används när man väljer att väga in poängtrenden i den långsiktiga planeraren. Backtesten
# säger att det gör prognosen marginellt sämre, så vikten hålls låg.
POINTS_TREND_WEIGHT_OPTION = 0.3


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
    recent_play: float | None = None,
    ppg_delta: float = 0.0,
    pm_per_game: float = 0.0,
) -> tuple[float, float]:
    """Förväntade poäng per lagmatch och speltidsandel.

    recent_play är speltidsandelen de senaste veckorna (se trend.py) och ppg_delta
    poängtrenden. Utelämnas de räknas bara säsongen.

    pm_per_game är plus/minus-poäng per spelad match. Plus/minus styrs till stor del av lagets
    skott- och räddningsprocent när spelaren är på isen (PDO), som brukar jämna ut sig. En
    spelare med mycket plus/minus-poäng har därför ofta haft tur, och en del av de poängen
    räknas bort. Gäller inte målvakter (de får inga plus/minus-poäng).
    """
    intercept, slope = prior
    prior_ppg = max(intercept + slope * price, 0.5)
    gp = games_played
    quality = (gp * ppg + params.prior_strength * prior_ppg) / (gp + params.prior_strength)
    if team_games == 0:
        return quality, 1.0
    # Lätt krympning så att en enstaka missad match inte slår för hårt
    play_rate = min(1.0, (gp + 0.5) / (team_games + 0.5))
    if recent_play is not None:
        play_rate = (1 - params.recent_play_weight) * play_rate + params.recent_play_weight * recent_play
    base = quality * play_rate
    per_game = (1 - params.form_weight) * base + params.form_weight * form
    per_game += params.points_trend_weight * ppg_delta * play_rate
    # Samma andel som spelarens egen statistik väger i krympningen ovan
    per_game -= params.pdo_weight * pm_per_game * gp / (gp + params.prior_strength) * play_rate
    return max(per_game, 0.0), play_rate


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
