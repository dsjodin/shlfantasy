"""Formtrend per spelare: pekar formen uppåt eller nedåt?

Trenden räknas ur poäng och matcher per matchvecka och jämför de senaste veckorna med
säsongen. Två saker mäts var för sig eftersom de beter sig olika:

- Poängtrend: poäng per spelad match de senaste veckorna mot säsongssnittet.
- Speltidstrend: andel av lagets matcher spelaren har spelat de senaste veckorna mot säsongen.

Backtesten (backtest.py) visar att speltidstrenden förbättrar prognosen, medan poängtrenden
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


@dataclass(frozen=True)
class WeekStat:
    gameweek: int
    games: int  # spelarens matcher
    points: int
    team_games: int  # lagets spelade matcher samma vecka
    pm: int = 0  # plus/minus-poäng


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

    if rec_play <= season_play - PLAY_SHIFT:
        direction, reason = "down", "Spelar mindre än tidigare"
    elif rec_play >= season_play + PLAY_SHIFT:
        direction, reason = "up", "Spelar mer än tidigare"
    else:
        threshold = max(0.6, 0.2 * abs(season_ppg))
        if delta >= threshold:
            direction, reason = "up", "Fler poäng per match senaste veckorna"
        elif delta <= -threshold:
            direction, reason = "down", "Färre poäng per match senaste veckorna"
        else:
            direction, reason = "flat", "Stabil"
    return Trend(direction, reason, season_ppg, rec_ppg, delta, season_play, rec_play, len(weeks))


def plus_minus_per_game(weeks: list[WeekStat]) -> float:
    games = sum(w.games for w in weeks)
    return sum(w.pm for w in weeks) / games if games else 0.0
