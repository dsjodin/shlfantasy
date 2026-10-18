from __future__ import annotations

import pytest

from app.datastore import Snapshot
from app.model import build_model
from app.squad import TeamState

CLUBS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
LAYOUT = {"GK": 2, "D": 4, "C": 2, "F": 4}


def make_snapshot() -> Snapshot:
    players = []
    pid = 1000
    for ci, club in enumerate(CLUBS):
        for pos, n in LAYOUT.items():
            for k in range(n):
                pid += 1
                price = round(4.0 + (k * 1.5) + ci * 0.3, 1)
                ppg = round(price * 0.6 + (1.0 if pos == "GK" else 0.0), 1)
                players.append(
                    {
                        "id": str(pid),
                        "name": f"{club} {pos}{k}",
                        "club": club,
                        "position": pos,
                        "status": "active",
                        "price": price,
                        "ownership": 1.0,
                        "games_played": 4,
                        "total_points": int(ppg * 4),
                        "ppg": ppg,
                        "form": ppg,
                        "breakdown": {},
                        "season": 2026,
                    }
                )
    gameweeks = [
        {"number": 1, "start": "2026-09-01", "end": "2026-09-07", "status": "completed", "csv_url": None},
        {"number": 2, "start": "2026-09-08", "end": "2026-09-14", "status": "upcoming", "csv_url": None},
        {"number": 3, "start": "2026-09-15", "end": "2026-09-21", "status": "upcoming", "csv_url": None},
    ]
    games = []
    # Vecka 1 (spelad): alla lag möts i par fyra gånger -> 4 lagmatcher var
    for day in ("2026-09-02", "2026-09-03", "2026-09-05", "2026-09-06"):
        for a, b in zip(CLUBS[::2], CLUBS[1::2]):
            games.append(_game(day, a, b, True))
    # Vecka 2: AAA spelar 3 matcher, FFF ingen, övriga 1–2
    for day, a, b in [
        ("2026-09-09", "AAA", "BBB"),
        ("2026-09-10", "AAA", "CCC"),
        ("2026-09-12", "AAA", "DDD"),
        ("2026-09-12", "EEE", "BBB"),
    ]:
        games.append(_game(day, a, b, False))
    # Vecka 3: alla spelar en match
    for a, b in zip(CLUBS[::2], CLUBS[1::2]):
        games.append(_game("2026-09-16", a, b, False))
    return Snapshot(season=2026, players=players, gameweeks=gameweeks, games=games, fetched_at="2026-09-08T00:00:00+00:00")


def _game(day: str, home: str, away: str, played: bool) -> dict:
    return {
        "id": f"{day}-{home}-{away}",
        "start": f"{day} 19:00:00",
        "date": day,
        "home": home,
        "away": away,
        "home_score": None,
        "away_score": None,
        "state": "post-game" if played else "pre-game",
        "played": played,
    }


@pytest.fixture
def snapshot() -> Snapshot:
    return make_snapshot()


@pytest.fixture
def model(snapshot):
    return build_model(snapshot)


def cheapest_valid_squad(model) -> list[str]:
    """Billigaste giltiga trupp (max 3 per lag)."""
    need = {"GK": 2, "D": 5, "C": 3, "F": 5}
    per_club: dict[str, int] = {}
    chosen = []
    for p in sorted(model.players.values(), key=lambda p: p.price):
        if need[p.position] and per_club.get(p.club, 0) < 3:
            chosen.append(p.id)
            need[p.position] -= 1
            per_club[p.club] = per_club.get(p.club, 0) + 1
    assert not any(need.values())
    return chosen


@pytest.fixture
def state(model) -> TeamState:
    return TeamState(player_ids=cheapest_valid_squad(model), bank=5.0, free_transfers=1)
