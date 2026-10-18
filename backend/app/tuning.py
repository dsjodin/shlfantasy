"""Automatisk justering av modellens vikter, en gång per ny slutrapporterad matchvecka.

Spärrar mot att modellen anpassar sig efter slumpen:
- Minst MIN_WEEKS testveckor krävs innan något justeras.
- Kandidaten tas fram på alla veckor utom de HOLDOUT senaste och prövas sedan på just
  dem – veckor den aldrig sett. Den nuvarande modellen prövas på samma veckor.
- Kandidaten tas i bruk bara om medelfelet blir minst MIN_IMPROVEMENT bättre och den
  bästa elvan inte blir märkbart sämre.
- Utan sparade priser (prognosarkivet) begränsas priset vikt, eftersom dagens pris
  annars ger priset en orättvis fördel i efterhand.
- Varje prövning loggas, även när inget byts.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .archive import PredictionArchive
from .backtest import PRIOR_GRID, PRIOR_GRID_WITH_ARCHIVED_PRICES, build_weeks, evaluate, grid_search
from .datastore import Snapshot, read_json, write_json
from .projection import DEFAULT_PARAMS, Params

MIN_WEEKS = 4
HOLDOUT = 2
MIN_IMPROVEMENT = 0.01  # 1 % lägre medelfel
MAX_LINEUP_DROP = 0.02  # bästa elvan får inte bli mer än 2 procentenheter sämre
MAX_LOG = 50


class ParamStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "params.json"
        self.version = 0

    def _data(self) -> dict[str, Any]:
        return read_json(self.path, {}) or {}

    def current(self) -> Params:
        saved = self._data().get("params")
        if not saved:
            return DEFAULT_PARAMS
        fields = Params.__dataclass_fields__
        return Params(**{k: v for k, v in saved.items() if k in fields})

    def log(self) -> list[dict[str, Any]]:
        return self._data().get("log", [])

    def last_evaluated_week(self) -> int:
        return self._data().get("last_week", 0)

    def maybe_tune(self, snap: Snapshot, archive: PredictionArchive | None = None) -> dict[str, Any] | None:
        """Prövar nya vikter om en ny matchvecka har slutrapporterats sedan sist."""
        weeks = build_weeks(snap, archive)
        if not weeks:
            return None
        latest = weeks[-1].number
        if latest <= self.last_evaluated_week():
            return None

        data = self._data()
        current = self.current()
        entry: dict[str, Any] = {
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "week": latest,
            "current": asdict(current),
        }
        if len(weeks) < MIN_WEEKS:
            entry.update(adopted=False, reason=f"För få spelade veckor ({len(weeks)} av minst {MIN_WEEKS}).")
        else:
            train, holdout = weeks[:-HOLDOUT], weeks[-HOLDOUT:]
            all_archived = all(w.archived_prices for w in weeks)
            prior_grid = PRIOR_GRID_WITH_ARCHIVED_PRICES if all_archived else PRIOR_GRID
            candidate, _ = grid_search(train, prior_grid)
            cur = evaluate(holdout, current)
            cand = evaluate(holdout, candidate)
            improvement = (cur["mae"] - cand["mae"]) / cur["mae"] if cur["mae"] else 0.0
            lineup_ok = cand["lineup_efficiency"] >= cur["lineup_efficiency"] - MAX_LINEUP_DROP
            adopted = candidate != current and improvement >= MIN_IMPROVEMENT and lineup_ok
            if candidate == current:
                reason = "Nuvarande vikter är fortfarande bäst."
            elif adopted:
                reason = f"Nya vikter {_pct(improvement)} bättre på vecka {', '.join(str(w.number) for w in holdout)}."
            elif not lineup_ok:
                reason = "Kandidaten valde sämre elva på testveckorna."
            else:
                reason = f"Förbättringen ({_pct(improvement)}) var för liten för att byta."
            entry.update(
                candidate=asdict(candidate),
                holdout_weeks=[w.number for w in holdout],
                current_mae=cur["mae"],
                candidate_mae=cand["mae"],
                current_lineup=cur["lineup_efficiency"],
                candidate_lineup=cand["lineup_efficiency"],
                adopted=adopted,
                reason=reason,
            )
            if adopted:
                data["params"] = asdict(candidate)
                self.version += 1

        data["last_week"] = latest
        data["log"] = ([entry] + data.get("log", []))[:MAX_LOG]
        write_json(self.path, data)
        return entry


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")
