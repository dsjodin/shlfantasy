"""Omvandlar modellobjekt till JSON-vänliga dictar för API:t och AI-verktygen."""

from __future__ import annotations

from datetime import date

from .model import Model, Player


def player_view(model: Model, p: Player, gameweeks: list[int], detailed: bool = False) -> dict:
    next_gw = gameweeks[0] if gameweeks else None
    today = date.today()
    view = {
        "id": p.id,
        "name": p.name,
        "club": p.club,
        "position": p.position,
        "status": p.status,
        "price": p.price,
        "ownership": p.ownership,
        "games_played": p.games_played,
        "total_points": p.total_points,
        "ppg": p.ppg,
        "form": p.form,
        "age": p.age_on(today),
        "xp_per_game": p.xp_per_game,
        "play_rate": round(p.play_rate, 2),
        "xp_next": p.xp.get(next_gw, 0.0) if next_gw else 0.0,
        "xp_horizon": round(p.xp_over(gameweeks), 2),
        "games_next": model.games_in(p.club, next_gw) if next_gw else 0,
        "xp": {gw: p.xp.get(gw, 0.0) for gw in gameweeks},
        "games": {gw: model.games_in(p.club, gw) for gw in gameweeks},
    }
    if detailed:
        view["breakdown"] = {k: v for k, v in p.breakdown.items() if v}
        view["history"] = p.history
        view["fixtures"] = {
            gw: [
                f"{'H' if f['home'] else 'B'} {f['opponent']} {f['date']}"
                for f in model.fixtures.get(p.club, {}).get(gw, [])
            ]
            for gw in gameweeks
        }
    return view


def compact_player(model: Model, p: Player, gameweeks: list[int]) -> dict:
    """Kompakt variant för AI-verktyg (sparar tokens)."""
    next_gw = gameweeks[0] if gameweeks else None
    return {
        "id": p.id,
        "name": p.name,
        "club": p.club,
        "pos": p.position,
        "status": p.status,
        "price": p.price,
        "gp": p.games_played,
        "pts": p.total_points,
        "ppg": p.ppg,
        "form": p.form,
        "own%": p.ownership,
        "age": p.age_on(date.today()),
        "xp_next": p.xp.get(next_gw, 0.0) if next_gw else 0.0,
        "games_next": model.games_in(p.club, next_gw) if next_gw else 0,
        "xp_horizon": round(p.xp_over(gameweeks), 1),
    }


def gameweek_view(model: Model) -> list[dict]:
    clubs = sorted(model.fixtures)
    return [
        {
            **{k: gw[k] for k in ("number", "start", "end", "status")},
            "games_per_club": {club: model.games_in(club, gw["number"]) for club in clubs},
        }
        for gw in model.gameweeks
    ]
