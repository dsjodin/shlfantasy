"""Sparar lagen per profil (en per familjemedlem) som JSON i DATA_DIR/teams/<id>.json."""

from __future__ import annotations

import re
import secrets
from dataclasses import asdict
from pathlib import Path

from .datastore import read_json, write_json
from .squad import TeamState

PROFILE_ID = re.compile(r"^[a-f0-9]{8}$")
MAX_NAME_LENGTH = 30


class ProfileNotFound(Exception):
    pass


class TeamStore:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "teams"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy(data_dir / "team.json")

    def _migrate_legacy(self, legacy: Path) -> None:
        """Före profilerna fanns ett enda lag i team.json – flytta det till en profil."""
        if legacy.exists() and not self.profiles():
            profile = self.create("Mitt lag")
            self.save(profile["id"], self._state(read_json(legacy, {}) or {}))
            legacy.rename(legacy.with_suffix(".json.migrated"))

    def _path(self, profile_id: str) -> Path:
        if not PROFILE_ID.match(profile_id or ""):
            raise ProfileNotFound(profile_id)
        return self.dir / f"{profile_id}.json"

    @staticmethod
    def _state(data: dict) -> TeamState:
        fields = TeamState.__dataclass_fields__
        return TeamState(**{k: v for k, v in data.items() if k in fields})

    def _read(self, profile_id: str) -> dict:
        data = read_json(self._path(profile_id))
        if data is None:
            raise ProfileNotFound(profile_id)
        return data

    def exists(self, profile_id: str) -> bool:
        try:
            return self._path(profile_id).exists()
        except ProfileNotFound:
            return False

    def profiles(self) -> list[dict[str, str]]:
        result = []
        for path in self.dir.glob("*.json"):
            data = read_json(path)
            if data and PROFILE_ID.match(path.stem):
                result.append({"id": path.stem, "name": data.get("name", path.stem)})
        return sorted(result, key=lambda p: p["name"].lower())

    def create(self, name: str) -> dict[str, str]:
        profile_id = secrets.token_hex(4)
        name = _clean_name(name)
        write_json(self._path(profile_id), {"name": name, "team": asdict(TeamState())})
        return {"id": profile_id, "name": name}

    def rename(self, profile_id: str, name: str) -> dict[str, str]:
        data = self._read(profile_id)
        data["name"] = _clean_name(name)
        write_json(self._path(profile_id), data)
        return {"id": profile_id, "name": data["name"]}

    def delete(self, profile_id: str) -> None:
        path = self._path(profile_id)
        if not path.exists():
            raise ProfileNotFound(profile_id)
        path.unlink()

    def load(self, profile_id: str) -> TeamState:
        return self._state(self._read(profile_id).get("team") or {})

    def get_extra(self, profile_id: str, key: str, default=None):
        """Övrig profildata (t.ex. AI-minnet) som ligger i samma fil som laget."""
        return self._read(profile_id).get(key, default)

    def set_extra(self, profile_id: str, key: str, value) -> None:
        data = self._read(profile_id)
        data[key] = value
        write_json(self._path(profile_id), data)

    def save(self, profile_id: str, state: TeamState) -> None:
        data = self._read(profile_id)
        data["team"] = asdict(state)
        write_json(self._path(profile_id), data)


def _clean_name(name: str) -> str:
    name = " ".join(name.split())[:MAX_NAME_LENGTH]
    if not name:
        raise ValueError("Namnet får inte vara tomt.")
    return name
