"""Sparar ditt eget lag (trupp, bank, gratisbyten, använda coachkort) som JSON."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .datastore import read_json, write_json
from .squad import TeamState


class TeamStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "team.json"

    def load(self) -> TeamState:
        data = read_json(self.path, {}) or {}
        fields = TeamState.__dataclass_fields__
        return TeamState(**{k: v for k, v in data.items() if k in fields})

    def save(self, state: TeamState) -> None:
        write_json(self.path, asdict(state))
