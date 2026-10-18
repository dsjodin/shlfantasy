"""Bygger en analysmodell av rådatan: förväntade poäng (xP) per spelare och matchvecka.

Modellen är medvetet enkel och transparent:

1. Kvalitet per spelad match = poäng per match (ppg), krympt mot ett pris-baserat
   förväntningsvärde för positionen när antalet matcher är litet. Fantasy SHL prissätter
   spelare efter förväntad poäng per match, så priset är en bra "prior".
2. Speltid = andel av lagets matcher spelaren har spelat (viktigt för t.ex. målvakter).
3. Formen (snitt senaste fem lagmatcher, inkl. nollor) vägs in för att fånga trender.
4. xP för en vecka = summan över lagets matcher den veckan av förväntat per lagmatch,
   justerat för motståndarens styrka, hemmaplan och skada/frånvaro.

Själva formeln ligger i projection.py och vikterna är framtagna med backtest.py.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .datastore import Snapshot
from .projection import DEFAULT_PARAMS, Params, TeamStrength, expected_per_game, game_multiplier, price_priors, team_strength
from .rules import POSITIONS

# Multiplikator per vecka framåt (0 = nästa vecka) beroende på status
STATUS_MULTIPLIERS = {
    "active": (1.0,),
    "unavailable": (0.5, 0.8, 0.95, 1.0),
    "injured": (0.0, 0.4, 0.75, 0.9, 1.0),
}


@dataclass
class Player:
    id: str
    name: str
    club: str
    position: str
    status: str
    price: float
    ownership: float
    games_played: int
    total_points: int
    ppg: float
    form: float
    breakdown: dict[str, int]
    birth_date: str | None = None
    play_rate: float = 1.0
    xp_per_game: float = 0.0
    xp: dict[int, float] = field(default_factory=dict)
    history: list[dict[str, int]] = field(default_factory=list)

    def age_on(self, day: date) -> int | None:
        if not self.birth_date:
            return None
        b = date.fromisoformat(self.birth_date)
        return day.year - b.year - ((day.month, day.day) < (b.month, b.day))

    def xp_over(self, gameweeks: list[int], discount: float = 1.0) -> float:
        return sum(self.xp.get(gw, 0.0) * discount**i for i, gw in enumerate(gameweeks))


@dataclass
class Model:
    season: int
    players: dict[str, Player]
    gameweeks: list[dict[str, Any]]
    games: list[dict[str, Any]]
    # {club: {gameweek: [{"opponent": "FBK", "home": True, "date": ...}, ...]}}
    fixtures: dict[str, dict[int, list[dict[str, Any]]]]
    fetched_at: str | None
    errors: list[str]
    strength: TeamStrength | None = None
    params: Params = DEFAULT_PARAMS

    @property
    def next_gameweek(self) -> int | None:
        """Första matchveckan som inte har startat – dit nya byten räknas."""
        return next((gw["number"] for gw in self.gameweeks if gw["status"] == "upcoming"), None)

    @property
    def current_gameweek(self) -> int | None:
        return next((gw["number"] for gw in self.gameweeks if gw["status"] == "ongoing"), None)

    def gameweek(self, number: int) -> dict[str, Any] | None:
        return next((gw for gw in self.gameweeks if gw["number"] == number), None)

    def horizon(self, weeks: int, start: int | None = None) -> list[int]:
        start = start or self.next_gameweek
        if start is None:
            return []
        return [gw["number"] for gw in self.gameweeks if gw["number"] >= start][:weeks]

    def games_in(self, club: str, gameweek: int) -> int:
        return len(self.fixtures.get(club, {}).get(gameweek, []))

    def find(self, query: str) -> list[Player]:
        q = query.strip().lower()
        if q in self.players:
            return [self.players[q]]
        exact = [p for p in self.players.values() if p.name.lower() == q]
        return exact or [p for p in self.players.values() if q in p.name.lower()]


def assign_gameweek(day: str, gameweeks: list[dict[str, Any]]) -> int | None:
    for gw in gameweeks:
        if gw["start"] <= day <= gw["end"]:
            return gw["number"]
    return None


def build_model(snap: Snapshot, params: Params = DEFAULT_PARAMS) -> Model:
    gameweeks = sorted(snap.gameweeks, key=lambda g: g["number"])

    fixtures: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    team_games_played: dict[str, int] = defaultdict(int)
    games = []
    for raw_game in snap.games:
        gw = assign_gameweek(raw_game["date"], gameweeks)
        g = {**raw_game, "gameweek": gw}
        games.append(g)
        if g["played"]:
            team_games_played[g["home"]] += 1
            team_games_played[g["away"]] += 1
        if gw is None:
            continue
        fixtures[g["home"]][gw].append({"opponent": g["away"], "home": True, "date": g["date"], "played": g["played"]})
        fixtures[g["away"]][gw].append({"opponent": g["home"], "home": False, "date": g["date"], "played": g["played"]})

    history: dict[str, list[dict[str, int]]] = defaultdict(list)
    for key in sorted(snap.gameweek_points, key=int):
        for pid, row in snap.gameweek_points[key].items():
            history[pid].append({"gameweek": int(key), **row})

    priors = price_priors(snap.players, POSITIONS)
    strength = team_strength((g for g in games if g["played"]), params.team_prior_games)
    birthdates = snap.birthdates
    upcoming = [gw["number"] for gw in gameweeks if gw["status"] == "upcoming"]

    players: dict[str, Player] = {}
    for raw in snap.players:
        if raw["position"] not in POSITIONS:
            continue
        p = Player(
            id=raw["id"],
            name=raw["name"],
            club=raw["club"],
            position=raw["position"],
            status=raw["status"],
            price=raw["price"],
            ownership=raw["ownership"],
            games_played=raw["games_played"],
            total_points=raw["total_points"],
            ppg=raw["ppg"],
            form=raw["form"],
            breakdown=raw["breakdown"],
            birth_date=birthdates.get(raw["id"]),
            history=history.get(raw["id"], []),
        )
        per_game, p.play_rate = expected_per_game(
            price=p.price,
            games_played=p.games_played,
            ppg=p.ppg,
            form=p.form,
            team_games=team_games_played.get(p.club, 0),
            prior=priors[p.position],
            params=params,
        )
        p.xp_per_game = round(per_game, 2)

        multipliers = STATUS_MULTIPLIERS.get(p.status, STATUS_MULTIPLIERS["active"])
        for i, gw in enumerate(upcoming):
            status_mult = multipliers[min(i, len(multipliers) - 1)]
            week = sum(
                game_multiplier(p.position, f["opponent"], f["home"], strength, params)
                for f in fixtures.get(p.club, {}).get(gw, [])
            )
            p.xp[gw] = round(per_game * week * status_mult, 2)
        players[p.id] = p

    return Model(
        season=snap.season,
        players=players,
        gameweeks=gameweeks,
        games=games,
        fixtures={club: dict(weeks) for club, weeks in fixtures.items()},
        fetched_at=snap.fetched_at,
        errors=snap.errors,
        strength=strength,
        params=params,
    )
