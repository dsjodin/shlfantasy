"""Matchschema och födelsedatum från shl.se:s publika API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

API = "https://www.shl.se/api/sports-v2"

# Fantasy SHL och shl.se använder olika förkortningar för ett par lag.
SHL_TO_FANTASY_CLUB = {"OHK": "ÖRE", "SAIK": "SKE"}

log = logging.getLogger(__name__)


def to_fantasy_club(code: str) -> str:
    return SHL_TO_FANTASY_CLUB.get(code, code)


async def _get_json(client: httpx.AsyncClient, path: str, **params) -> Any:
    response = await client.get(f"{API}/{path}", params=params or None)
    response.raise_for_status()
    return response.json()


async def find_season(client: httpx.AsyncClient, season_code: int) -> dict[str, str]:
    """Hittar uuid:er för SHL:s grundserie för en given säsong (startår)."""
    data = await _get_json(client, "season-series-game-types-filter")
    season = next(s for s in data["season"] if s["code"] == str(season_code))
    series = next(s for s in data["series"] if s["code"] == "SHL")
    game_type = next(g for g in data["gameType"] if g["code"] == "regular")
    return {"season": season["uuid"], "series": series["uuid"], "game_type": game_type["uuid"]}


def parse_schedule(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    games = []
    for g in data["gameInfo"]:
        home, away = g["homeTeamInfo"], g["awayTeamInfo"]
        games.append(
            {
                "id": g["uuid"],
                "start": g["startDateTime"],  # lokal svensk tid, "YYYY-MM-DD HH:MM:SS"
                "date": g["startDateTime"][:10],
                "home": to_fantasy_club(home["code"]),
                "away": to_fantasy_club(away["code"]),
                "home_score": home.get("score"),
                "away_score": away.get("score"),
                "state": g.get("state"),
                "played": g.get("state") == "post-game",
            }
        )
    teams = [
        {"uuid": t["uuid"], "club": to_fantasy_club(t["teamCode"])}
        for t in data.get("teamList", [])
        if t.get("teamCode")
    ]
    return games, teams


async def fetch_schedule(client: httpx.AsyncClient, season_code: int):
    ids = await find_season(client, season_code)
    data = await _get_json(
        client,
        "game-schedule",
        seasonUuid=ids["season"],
        seriesUuid=ids["series"],
        gameTypeUuid=ids["game_type"],
        gamePlace="all",
        played="all",
    )
    return parse_schedule(data)


async def fetch_birthdates(
    client: httpx.AsyncClient,
    teams: list[dict[str, str]],
    known_athletes: set[str],
    concurrency: int = 4,
) -> dict[str, dict[str, str]]:
    """Hämtar födelsedatum för spelare vi inte redan känner till.

    Returnerar {athlete_uuid: {"player_id": <Fantasy/ISA-id>, "birth_date": "YYYY-MM-DD"}}.
    """
    athlete_uuids: list[str] = []
    for team in teams:
        try:
            groups = await _get_json(client, f"athletes/by-team-uuid/{team['uuid']}")
        except httpx.HTTPError as exc:
            log.warning("Kunde inte hämta trupp för %s: %s", team["club"], exc)
            continue
        for group in groups:
            for p in group.get("players", []):
                if p.get("uuid") and p["uuid"] not in known_athletes:
                    athlete_uuids.append(p["uuid"])

    sem = asyncio.Semaphore(concurrency)
    result: dict[str, dict[str, str]] = {}

    async def one(uuid: str) -> None:
        async with sem:
            try:
                data = await _get_json(client, f"athlete-details/{uuid}")
            except httpx.HTTPError as exc:
                log.warning("Kunde inte hämta spelare %s: %s", uuid, exc)
                return
        athlete = data.get("athleteData") or {}
        isa = next(
            (e["extId"] for e in athlete.get("playerExtIds", []) if e.get("extIdType", {}).get("code") == "isa"),
            None,
        )
        result[uuid] = {"player_id": str(isa) if isa else "", "birth_date": athlete.get("dateOfBirth") or ""}

    await asyncio.gather(*(one(u) for u in athlete_uuids))
    return result
