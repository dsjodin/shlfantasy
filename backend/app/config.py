"""Inställningar som läses från miljövariabler."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    static_dir: Path | None
    refresh_minutes: int
    claude_model: str
    claude_effort: str
    ai_enabled: bool


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    static = os.environ.get("STATIC_DIR")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return Settings(
        data_dir=data_dir,
        static_dir=Path(static).resolve() if static else None,
        refresh_minutes=int(os.environ.get("REFRESH_MINUTES", "60")),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
        claude_effort=os.environ.get("CLAUDE_EFFORT", "medium"),
        ai_enabled=has_key,
    )
