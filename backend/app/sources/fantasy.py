"""Publik statistikexport från Fantasy SHL (https://fantasy.shl.se/statistics)."""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx

BASE_URL = "https://fantasy.shl.se/statistics"

POINT_COLUMNS = (
    "goals_points",
    "assists_points",
    "game_winning_goals_points",
    "shorthanded_goals_points",
    "plus_minus_points",
    "time_on_ice_points",
    "shots_on_goal_points",
    "faceoffs_won_points",
    "blocked_shots_points",
    "penalty_minutes_points",
    "hits_points",
    "saves_points",
    "goals_against_points",
    "shutouts_points",
    "wins_points",
    "overtime_wins_points",
    "overtime_losses_points",
    "goalkeeper_appearances_points",
    "other_points",
)


def _num(value: str | None, cast=float, default=0):
    if value is None or value == "":
        return default
    try:
        return cast(value)
    except ValueError:
        return default


def parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def parse_players(text: str) -> list[dict[str, Any]]:
    players = []
    for row in parse_csv(text):
        players.append(
            {
                "id": row["player_shl_id"].strip(),
                "name": row["player_name"].strip(),
                "club": row["club_code"].strip(),
                "position": row.get("position", "").strip() or None,
                "status": row.get("status", "active").strip() or "active",
                "price": _num(row.get("price_millions")),
                "ownership": _num(row.get("ownership_percent")),
                "games_played": _num(row.get("games_played"), int),
                "total_points": _num(row.get("total_fantasy_points"), int),
                "ppg": _num(row.get("fantasy_points_per_game")),
                "form": _num(row.get("form")),
                "breakdown": {c: _num(row.get(c), int) for c in POINT_COLUMNS},
                "season": _num(row.get("season"), int),
            }
        )
    return players


def parse_gameweeks(text: str) -> list[dict[str, Any]]:
    return [
        {
            "number": int(row["gameweek"]),
            "start": row["start_date"],
            "end": row["end_date"],
            "status": row["status"],
            "csv_url": row.get("csv_url") or None,
        }
        for row in parse_csv(text)
    ]


def parse_gameweek_points(text: str) -> dict[str, dict[str, Any]]:
    """Returnerar {player_id: {"games": n, "points": p}} för en matchvecka."""
    result = {}
    for row in parse_csv(text):
        result[row["player_shl_id"].strip()] = {
            "games": _num(row.get("games_played"), int),
            "points": _num(row.get("total_fantasy_points"), int),
        }
    return result


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


async def fetch_players(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    return parse_players(await fetch_text(client, f"{BASE_URL}/players.csv"))


async def fetch_gameweeks(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    return parse_gameweeks(await fetch_text(client, f"{BASE_URL}/gameweeks.csv"))


async def fetch_gameweek_points(client: httpx.AsyncClient, number: int) -> dict[str, dict[str, Any]]:
    return parse_gameweek_points(await fetch_text(client, f"{BASE_URL}/gameweeks/{number}.csv"))
