"""Arkiv över modellens prognoser per matchvecka.

Inför varje matchvecka sparas priser, status och prognos för alla spelare. Filen skrivs om
vid varje uppdatering tills veckan startar och fryses därefter – den sista versionen är
alltså den som gällde vid deadline. Det ger en ärlig mätning i efterhand (exakt vad
modellen trodde, med dåtidens priser) och bygger upp historik över säsongen.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .datastore import read_json, write_json
from .model import Model


class PredictionArchive:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "history"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, gameweek: int) -> Path:
        return self.dir / f"gw{int(gameweek)}.json"

    def record(self, model: Model) -> int | None:
        gw = model.next_gameweek
        info = model.gameweek(gw) if gw else None
        if not info or info["status"] != "upcoming":
            return None
        write_json(
            self._path(gw),
            {
                "gameweek": gw,
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "params": asdict(model.params),
                "players": {
                    p.id: {
                        "price": p.price,
                        "status": p.status,
                        "position": p.position,
                        "club": p.club,
                        "xp": p.xp.get(gw, 0.0),
                        "xp_per_game": p.xp_per_game,
                        "games": model.games_in(p.club, gw),
                    }
                    for p in model.players.values()
                },
            },
        )
        return gw

    def load(self, gameweek: int) -> dict[str, Any] | None:
        return read_json(self._path(gameweek))

    def weeks(self) -> list[int]:
        return sorted(int(p.stem[2:]) for p in self.dir.glob("gw*.json") if p.stem[2:].isdigit())
