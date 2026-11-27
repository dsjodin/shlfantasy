"""Formtrend per spelare: pekar formen uppåt eller nedåt?

Trenden räknas ur poäng och matcher per matchvecka och jämför de senaste veckorna med
säsongen. Två saker mäts var för sig eftersom de beter sig olika:

- Poängtrend: poäng per spelad match de senaste veckorna mot säsongssnittet.
- Speltidstrend: andel av lagets matcher spelaren har spelat de senaste veckorna mot säsongen.

- Istidstrend: minuter per match de senaste två veckorna mot säsongen (från shl.se:s
  matchrapporter). Den mäter rollen direkt: en spelare som flyttas upp får mer istid innan
  poängen syns.

Backtesten (backtest.py) visar att speltids- och istidstrenden förbättrar prognosen, medan poängtrenden
gör den något sämre. Veckopoäng i hockey är så slumpmässiga att en het period oftast inte
håller i sig. Därför används speltidstrenden alltid i xP, medan poängtrenden bara visas och
kan vägas in som ett val i den långsiktiga planeraren.

Ren funktion av indata så att samma kod används både framåt och i backtesten.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

POINTS_HALF_LIFE = 2.0  # veckor: hur snabbt äldre veckor tappar vikt i poängtrenden
MIN_GAMES = 4  # färre spelade matcher än så ger ingen trend
PLAY_SHIFT = 0.25  # så här stor förändring i speltidsandel räknas som en trend
TOI_SHIFT = 0.15  # så här stor relativ förändring i istid räknas som en trend
TOI_RECENT_WEEKS = 2
TOI_MIN_GAMES = 4


@dataclass(frozen=True)
class WeekStat:
    gameweek: int
    games: int  # spelarens matcher
    points: int
    team_games: int  # lagets spelade matcher samma vecka
    pm: int = 0  # plus/minus-poäng
    toi: int = 0  # istid i sekunder enligt matchrapporterna
    toi_games: int = 0  # matcher med istid i matchrapporterna


@dataclass(frozen=True)
class Trend:
    direction: str  # "up" | "down" | "flat"
    reason: str  # kort förklaring på svenska
    season_ppg: float
    recent_ppg: float
    ppg_delta: float  # recent − season, poäng per spelad match
    season_play_rate: float
    recent_play_rate: float
    weeks: int  # antal veckor med lagmatcher som ligger till grund
    season_toi: float | None = None  # minuter per match
    recent_toi: float | None = None

    def to_dict(self) -> dict:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in asdict(self).items()}


FLAT = Trend("flat", "För få matcher för en trend", 0.0, 0.0, 0.0, 1.0, 1.0, 0)


def _decayed(weeks: list[WeekStat], half_life: float, value, weight) -> float | None:
    if not weeks:
        return None
    last = weeks[-1].gameweek
    lam = math.log(2) / half_life
    num = den = 0.0
    for w in weeks:
        k = math.exp(-lam * (last - w.gameweek)) * weight(w)
        num += k * value(w)
        den += k
    return num / den if den else None


def recent_play_rate(weeks: list[WeekStat], half_life: float) -> float | None:
    """Andel av lagets matcher spelaren har spelat, där senaste veckorna väger mest."""
    weeks = [w for w in weeks if w.team_games > 0]
    return _decayed(weeks, half_life, lambda w: min(w.games / w.team_games, 1.0), lambda w: w.team_games)


def recent_ppg(weeks: list[WeekStat], half_life: float = POINTS_HALF_LIFE) -> float | None:
    """Poäng per spelad match, där senaste veckorna väger mest."""
    weeks = [w for w in weeks if w.games > 0]
    return _decayed(weeks, half_life, lambda w: w.points / w.games, lambda w: w.games)


def toi_minutes(weeks: list[WeekStat]) -> tuple[float, float] | None:
    """(säsong, senaste två veckorna) i minuter per match, eller None om underlaget är för litet.
    De senaste veckorna räknas från lagets senaste vecka, så en spelare som varit borta två
    veckor får ingen istidstrend (frånvaron hanteras av speltid och status)."""
    games = sum(w.toi_games for w in weeks)
    if games < TOI_MIN_GAMES or not weeks:
        return None
    last = max(w.gameweek for w in weeks)
    recent = [w for w in weeks if w.gameweek > last - TOI_RECENT_WEEKS]
    recent_games = sum(w.toi_games for w in recent)
    if not recent_games:
        return None
    season = sum(w.toi for w in weeks) / games / 60
    return season, sum(w.toi for w in recent) / recent_games / 60


def toi_ratio(weeks: list[WeekStat]) -> float | None:
    """Istid senaste veckorna delat med säsongens. >1 = mer istid än tidigare."""
    minutes = toi_minutes(weeks)
    if not minutes or not minutes[0]:
        return None
    return minutes[1] / minutes[0]


def toi_by_week(
    boxscores: dict[str, dict[str, int]], game_weeks: dict[str, int]
) -> dict[str, dict[int, tuple[int, int]]]:
    """Summerar matchrapporterna till {player_id: {matchvecka: (sekunder, matcher)}}."""
    result: dict[str, dict[int, tuple[int, int]]] = {}
    for game_id, players in boxscores.items():
        gw = game_weeks.get(game_id)
        if gw is None:
            continue
        for pid, seconds in players.items():
            weeks = result.setdefault(pid, {})
            sec, n = weeks.get(gw, (0, 0))
            weeks[gw] = (sec + seconds, n + 1)
    return result


def compute(weeks: list[WeekStat], play_half_life: float) -> Trend:
    weeks = sorted((w for w in weeks if w.team_games > 0), key=lambda w: w.gameweek)
    games = sum(w.games for w in weeks)
    team_games = sum(w.team_games for w in weeks)
    if games < MIN_GAMES or not team_games:
        return FLAT
    season_ppg = sum(w.points for w in weeks) / games
    season_play = min(games / team_games, 1.0)
    rec_ppg = recent_ppg(weeks)
    rec_play = recent_play_rate(weeks, play_half_life)
    rec_ppg = season_ppg if rec_ppg is None else rec_ppg
    rec_play = season_play if rec_play is None else rec_play
    delta = rec_ppg - season_ppg
    minutes = toi_minutes(weeks)
    toi_change = minutes[1] / minutes[0] - 1 if minutes and minutes[0] else 0.0

    if rec_play <= season_play - PLAY_SHIFT:
        direction, reason = "down", "Spelar mindre än tidigare"
    elif rec_play >= season_play + PLAY_SHIFT:
        direction, reason = "up", "Spelar mer än tidigare"
    elif toi_change <= -TOI_SHIFT:
        direction, reason = "down", "Mindre istid än tidigare"
    elif toi_change >= TOI_SHIFT:
        direction, reason = "up", "Mer istid än tidigare"
    else:
        threshold = max(0.6, 0.2 * abs(season_ppg))
        if delta >= threshold:
            direction, reason = "up", "Fler poäng per match senaste veckorna"
        elif delta <= -threshold:
            direction, reason = "down", "Färre poäng per match senaste veckorna"
        else:
            direction, reason = "flat", "Stabil"
    return Trend(
        direction,
        reason,
        season_ppg,
        rec_ppg,
        delta,
        season_play,
        rec_play,
        len(weeks),
        minutes[0] if minutes else None,
        minutes[1] if minutes else None,
    )


def plus_minus_per_game(weeks: list[WeekStat]) -> float:
    games = sum(w.games for w in weeks)
    return sum(w.pm for w in weeks) / games if games else 0.0


def spike_per_game(weeks: list[WeekStat]) -> float:
    """Hur mycket spelarens bästa vecka ligger över en typisk vecka, utslaget per spelad match
    över säsongen. En enda vecka med 45 poäng drar annars upp snittet långt efteråt, men
    sådana veckor upprepas sällan (se README, "En extrem vecka")."""
    played = [w for w in weeks if w.games > 0]
    games = sum(w.games for w in played)
    if len(played) < 3 or not games:
        return 0.0
    rates = sorted(w.points / w.games for w in played)
    mid = len(rates) // 2
    typical = rates[mid] if len(rates) % 2 else (rates[mid - 1] + rates[mid]) / 2
    best = max(played, key=lambda w: w.points / w.games)
    return max(0.0, (best.points - typical * best.games) / games)


STABILITY_MIN_WEEKS = 3


def stability(weeks: list[WeekStat]) -> dict | None:
    """Nyckeltal för hur jämnt spelaren levererar, för information (påverkar inte xP).

    best_week_share: andel av säsongens poäng från bästa veckan.
    ppg_excl_best: poäng per match utan bästa veckan.
    median_week: medianpoäng per vecka (veckor där spelaren spelat minst en match).
    week_sd: spridning (standardavvikelse) i poäng per vecka.
    """
    played = [w for w in weeks if w.games > 0]
    if len(played) < STABILITY_MIN_WEEKS:
        return None
    points = [w.points for w in played]
    total = sum(points)
    games = sum(w.games for w in played)
    best = max(played, key=lambda w: w.points)
    ordered = sorted(points)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    mean = total / len(points)
    sd = math.sqrt(sum((x - mean) ** 2 for x in points) / len(points))
    rest_games = games - best.games
    return {
        "best_week": best.gameweek,
        "best_week_points": best.points,
        "best_week_share": round(best.points / total, 2) if total > 0 else None,
        "ppg_excl_best": round((total - best.points) / rest_games, 2) if rest_games else None,
        "median_week": round(median, 1),
        "week_sd": round(sd, 1),
        "weeks": len(played),
    }
