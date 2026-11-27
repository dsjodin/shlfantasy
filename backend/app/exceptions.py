"""Manuella undantag för frånvaro: varför en spelare har missat eller kommer att missa matcher.

Statistiken säger bara att en spelare inte spelade, inte varför. En spelare som är borta av
privata skäl eller vilas har inte tappat sin plats, men utan undantag sänker frånvaron hans
speltidsandel och därmed xP. Undantagen läggs för hand i DATA_DIR/exceptions.json:

    [
      {"player_id": "1674", "reason": "privat", "from": "2026-11-20", "to": "2026-11-22",
       "expected_return": "2026-11-25", "note": "Blev pappa"}
    ]

- reason: privat | vila | skada | avstängning
- from: första dagen borta. to: sista dagen (valfri, standard = from).
- expected_return: dag spelaren väntas spela igen (valfri).

Effekt:
- privat och vila: missade lagmatcher inom [from, to] räknas inte i speltidsandelen.
- skada och avstängning: andelen räknas som vanligt (det är en verklig frånvaro som statusen
  redan hanterar), men undantaget syns i spelarens data.
- Kommande matcher inom [from, to] eller före expected_return räknas som 0. Har undantaget ett
  återkomstdatum ersätter det statusens allmänna nedtrappning för kommande veckor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from .datastore import read_json
from .trend import WeekStat

log = logging.getLogger(__name__)

REASONS = ("privat", "vila", "skada", "avstängning")
EXCUSED_REASONS = ("privat", "vila")  # påverkar inte speltidsandelen
FILE_NAME = "exceptions.json"


@dataclass(frozen=True)
class Absence:
    player_id: str
    reason: str
    start: date
    end: date
    expected_return: date | None = None
    note: str = ""

    @property
    def excused(self) -> bool:
        return self.reason in EXCUSED_REASONS

    def unavailable_on(self, day: date) -> bool:
        """Borta en viss dag: inom perioden, eller före återkomstdatumet."""
        if self.start <= day <= self.end:
            return True
        return self.expected_return is not None and self.start <= day < self.expected_return

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "expected_return": self.expected_return.isoformat() if self.expected_return else None,
            "note": self.note,
        }


def path_for(data_dir: Path) -> Path:
    return data_dir / FILE_NAME


def parse(raw: Any) -> tuple[list[Absence], list[str]]:
    """Validerar rader. Felaktiga rader hoppas över och beskrivs i felistan."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["Frånvarofilen ska innehålla en lista."]
    result: list[Absence] = []
    errors: list[str] = []
    for i, row in enumerate(raw, start=1):
        try:
            if not isinstance(row, dict):
                raise ValueError("raden är inte ett objekt")
            pid = str(row.get("player_id") or "").strip()
            if not pid:
                raise ValueError("player_id saknas")
            reason = str(row.get("reason") or "").strip().lower()
            if reason not in REASONS:
                raise ValueError(f"okänd orsak '{row.get('reason')}' (tillåtna: {', '.join(REASONS)})")
            start = date.fromisoformat(str(row["from"]))
            end = date.fromisoformat(str(row["to"])) if row.get("to") else start
            if end < start:
                raise ValueError("to är före from")
            ret = date.fromisoformat(str(row["expected_return"])) if row.get("expected_return") else None
            if ret is not None and ret < start:
                raise ValueError("expected_return är före from")
            result.append(Absence(pid, reason, start, end, ret, str(row.get("note") or "")))
        except (KeyError, ValueError, TypeError) as exc:
            msg = f"Frånvarofilen rad {i}: {exc}"
            log.warning(msg)
            errors.append(msg)
    return result, errors


def load(data_dir: Path) -> tuple[list[Absence], list[str]]:
    path = path_for(data_dir)
    if not path.exists():
        return [], []
    raw = read_json(path, default=False)
    if raw is False:
        return [], [f"Frånvarofilen {path.name} är inte giltig JSON."]
    return parse(raw)


def by_player(absences: list[Absence]) -> dict[str, list[Absence]]:
    out: dict[str, list[Absence]] = {}
    for a in absences:
        out.setdefault(a.player_id, []).append(a)
    return out


def excused_team_games(absences: list[Absence], club_games: list[dict[str, Any]]) -> dict[int, int]:
    """Lagets spelade matcher per matchvecka som täcks av ett undantag med orsak privat/vila.
    club_games: lagets matcher med 'date', 'gameweek' och 'played'."""
    out: dict[int, int] = {}
    excused = [a for a in absences if a.excused]
    if not excused:
        return out
    for g in club_games:
        if not g.get("played") or not g.get("gameweek"):
            continue
        day = date.fromisoformat(g["date"])
        if any(a.start <= day <= a.end for a in excused):
            out[g["gameweek"]] = out.get(g["gameweek"], 0) + 1
    return out


def adjust_weeks(weeks: list[WeekStat], excused: dict[int, int]) -> tuple[list[WeekStat], int]:
    """Tar bort ursäktade lagmatcher ur nämnaren. Aldrig fler än spelaren faktiskt missade
    samma vecka, så andelen kan inte bli över 1 om han ändå spelade."""
    if not excused:
        return weeks, 0
    out, total = [], 0
    for w in weeks:
        missed = max(0, w.team_games - w.games)
        n = min(excused.get(w.gameweek, 0), missed)
        total += n
        out.append(replace(w, team_games=w.team_games - n) if n else w)
    return out, total


def availability(absences: list[Absence], games: list[dict[str, Any]]) -> float | None:
    """Andel av en veckas kommande matcher spelaren kan spela, eller None om inget undantag
    berör veckan."""
    if not absences or not games:
        return None
    days = [date.fromisoformat(g["date"]) for g in games]
    if not any(a.unavailable_on(d) for a in absences for d in days):
        return None
    available = sum(1 for d in days if not any(a.unavailable_on(d) for a in absences))
    return available / len(days)


def overrides_status(absences: list[Absence], last_team_game: date | None) -> bool:
    """Undantaget ersätter statusens allmänna nedtrappning när det gäller just nu (perioden når
    fram till lagets senaste match, eller återkomsten ligger efter den) och säger något om när
    spelaren är tillbaka: orsaken är privat/vila, eller ett återkomstdatum är angivet. En skada
    utan återkomstdatum behåller den vanliga nedtrappningen."""
    if last_team_game is None:
        return False
    return any(
        (a.excused or a.expected_return is not None)
        and (a.end >= last_team_game or (a.expected_return is not None and a.expected_return > last_team_game))
        for a in absences
    )
