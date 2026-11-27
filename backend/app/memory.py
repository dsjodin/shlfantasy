"""AI-rådgivarens minne per profil: anteckningar (preferenser, beslut) och byteshistorik.

Byten loggas automatiskt när de genomförs i appen. Utfallet räknas fram i efterhand:
hur många poäng de köpta spelarna tog jämfört med de sålda, från bytets första
matchvecka och framåt.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from .model import Model
from .team_store import TeamStore

MAX_NOTES = 50
MAX_NOTE_LENGTH = 300
MAX_TRANSFERS = 200


class ProfileMemory:
    def __init__(self, store: TeamStore, profile_id: str):
        self.store = store
        self.profile_id = profile_id

    def _get(self) -> dict[str, list]:
        memory = self.store.get_extra(self.profile_id, "memory") or {}
        return {"notes": memory.get("notes", []), "transfers": memory.get("transfers", [])}

    def _set(self, memory: dict[str, list]) -> None:
        self.store.set_extra(self.profile_id, "memory", memory)

    def notes(self) -> list[dict[str, str]]:
        return self._get()["notes"]

    def add_note(self, text: str) -> dict[str, str]:
        text = " ".join(text.split())[:MAX_NOTE_LENGTH]
        if not text:
            raise ValueError("Tom anteckning.")
        memory = self._get()
        note = {"id": secrets.token_hex(3), "text": text, "created": _now()}
        memory["notes"] = (memory["notes"] + [note])[-MAX_NOTES:]
        self._set(memory)
        return note

    def delete_note(self, note_id: str) -> bool:
        memory = self._get()
        before = len(memory["notes"])
        memory["notes"] = [n for n in memory["notes"] if n["id"] != note_id]
        self._set(memory)
        return len(memory["notes"]) < before

    def transfers(self) -> list[dict[str, Any]]:
        return self._get()["transfers"]

    def log_transfer(self, model: Model, out_ids: list[str], in_ids: list[str], evaluation: dict[str, Any]) -> None:
        def player(pid: str) -> dict[str, Any]:
            p = model.players[pid]
            return {"id": pid, "name": p.name, "club": p.club, "position": p.position, "price": p.price}

        memory = self._get()
        memory["transfers"] = (
            memory["transfers"]
            + [
                {
                    "date": _now(),
                    "gameweek": model.next_gameweek,
                    "out": [player(pid) for pid in out_ids],
                    "in": [player(pid) for pid in in_ids],
                    "penalty": evaluation["penalty"],
                    "expected_gain": evaluation["xp_gain_horizon"],
                    "horizon_weeks": evaluation["gameweeks"],
                }
            ]
        )[-MAX_TRANSFERS:]
        self._set(memory)


def transfer_outcomes(model: Model, transfers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Faktiskt utfall för varje loggat byte: poäng för köpta minus sålda spelare."""
    completed = {gw["number"] for gw in model.gameweeks if gw["status"] == "completed"}
    result = []
    for t in transfers:
        start = t.get("gameweek") or 0
        weeks = sorted(w for w in completed if w >= start)

        def points(pid: str) -> int:
            p = model.players.get(pid)
            if not p:
                return 0
            return sum(h["points"] for h in p.history if h["gameweek"] in weeks)

        in_pts = sum(points(p["id"]) for p in t["in"])
        out_pts = sum(points(p["id"]) for p in t["out"])
        result.append(
            {
                **t,
                "weeks_played": weeks,
                "in_points": in_pts,
                "out_points": out_pts,
                "net_points": in_pts - out_pts - t.get("penalty", 0) if weeks else None,
            }
        )
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
