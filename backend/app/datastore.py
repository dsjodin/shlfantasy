"""Hämtar, cachar och håller aktuell data i minnet.

All data sparas även som JSON i DATA_DIR så att appen fungerar om källorna är nere.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .sources import fantasy, shl

log = logging.getLogger(__name__)

USER_AGENT = "shlfantasy-helper/0.1 (personligt verktyg)"
BIRTHDATE_REFRESH_DAYS = 7


@dataclass
class Snapshot:
    season: int = 0
    players: list[dict[str, Any]] = field(default_factory=list)
    gameweeks: list[dict[str, Any]] = field(default_factory=list)
    games: list[dict[str, Any]] = field(default_factory=list)
    teams: list[dict[str, str]] = field(default_factory=list)
    # {gameweek: {player_id: {"games": n, "points": p}}}
    gameweek_points: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    final_gameweeks: list[str] = field(default_factory=list)  # avslutade och korrigerade
    # {athlete_uuid: {"player_id": ..., "birth_date": ...}}
    athletes: dict[str, dict[str, str]] = field(default_factory=dict)
    athletes_fetched_at: str | None = None
    fetched_at: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def birthdates(self) -> dict[str, str]:
        return {a["player_id"]: a["birth_date"] for a in self.athletes.values() if a["player_id"] and a["birth_date"]}


def write_json(path: Path, data: Any) -> None:
    """Skriver atomiskt så att en krasch aldrig lämnar en halv fil."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class DataStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "snapshot.json"
        cached = read_json(self.path, {}) or {}
        self.snapshot = Snapshot(**{k: v for k, v in cached.items() if k in Snapshot.__dataclass_fields__})
        self.version = 0
        self._lock = asyncio.Lock()

    @property
    def is_loaded(self) -> bool:
        return bool(self.snapshot.players)

    async def refresh(self, include_birthdates: bool | None = None) -> Snapshot:
        async with self._lock:
            snap = Snapshot(**asdict(self.snapshot))
            snap.errors = []
            async with httpx.AsyncClient(
                timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True
            ) as client:
                try:
                    snap.players = await fantasy.fetch_players(client)
                    snap.season = next((p["season"] for p in snap.players if p["season"]), snap.season)
                    snap.gameweeks = await fantasy.fetch_gameweeks(client)
                except httpx.HTTPError as exc:
                    snap.errors.append(f"Fantasy SHL: {exc}")
                    log.exception("Kunde inte hämta Fantasy SHL-data")

                await self._refresh_gameweek_points(client, snap)

                try:
                    snap.games, snap.teams = await shl.fetch_schedule(client, snap.season)
                except (httpx.HTTPError, StopIteration, KeyError) as exc:
                    snap.errors.append(f"Matchschema: {exc!r}")
                    log.exception("Kunde inte hämta matchschema")

                if include_birthdates is None:
                    include_birthdates = _is_stale(snap.athletes_fetched_at, BIRTHDATE_REFRESH_DAYS)
                if include_birthdates and snap.teams:
                    try:
                        new = await shl.fetch_birthdates(client, snap.teams, set(snap.athletes))
                        snap.athletes.update(new)
                        snap.athletes_fetched_at = _now()
                    except httpx.HTTPError as exc:
                        snap.errors.append(f"Födelsedatum: {exc}")

            snap.fetched_at = _now()
            self.snapshot = snap
            self.version += 1
            write_json(self.path, asdict(snap))
            log.info(
                "Data uppdaterad: %d spelare, %d matcher, %d födelsedatum",
                len(snap.players),
                len(snap.games),
                len(snap.birthdates),
            )
            return snap

    async def _refresh_gameweek_points(self, client: httpx.AsyncClient, snap: Snapshot) -> None:
        for gw in snap.gameweeks:
            key = str(gw["number"])
            # Avslutade veckor hämtas om en gång (för korrigeringar), pågående varje gång.
            if gw["status"] == "upcoming":
                continue
            if key in snap.final_gameweeks and key in snap.gameweek_points:
                continue
            try:
                points = await fantasy.fetch_gameweek_points(client, gw["number"])
            except httpx.HTTPError as exc:
                snap.errors.append(f"Matchvecka {key}: {exc}")
                continue
            snap.gameweek_points[key] = points
            if gw["status"] == "completed" and _days_since(gw["end"]) >= 2:
                snap.final_gameweeks.append(key)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_stale(timestamp: str | None, days: int) -> bool:
    if not timestamp:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).days >= days


def _days_since(date_str: str) -> int:
    return (datetime.now(timezone.utc).date() - datetime.fromisoformat(date_str).date()).days
