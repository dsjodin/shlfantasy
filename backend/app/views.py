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
        "trend": p.trend.to_dict(),
        "stability": p.stability,
        "absence": p.absence,
    }
    if detailed:
        view["adjustments"] = {
            "hot_week_penalty": p.hot_week_penalty,
            "spike_per_game": round(model.params.spike_weight * p.spike, 2),
        }
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
        "trend": p.trend.direction,
        "trend_ppg_delta": round(p.trend.ppg_delta, 1),
        "recent_play_rate": round(p.trend.recent_play_rate, 2),
        "toi_min": round(p.trend.recent_toi, 1) if p.trend.recent_toi else None,
        "toi_min_season": round(p.trend.season_toi, 1) if p.trend.season_toi else None,
        **{
            k: (p.stability or {}).get(k)
            for k in ("best_week_share", "ppg_excl_best", "median_week", "week_sd")
        },
        **({"absence": _absence_text(p.absence)} if p.absence else {}),
    }


REASON_TEXT = {"privat": "privata skäl", "vila": "vila", "skada": "skada", "avstängning": "avstängning"}


def _absence_text(absence: dict) -> str:
    """Kort förklaring av ett frånvaroundantag, för AI-verktygen."""
    parts = []
    for a in absence["absences"]:
        period = a["from"] if a["from"] == a["to"] else f"{a['from']}–{a['to']}"
        ret = f", väntas tillbaka {a['expected_return']}" if a["expected_return"] else ""
        parts.append(f"Borta {period} ({REASON_TEXT.get(a['reason'], a['reason'])}{ret})")
    if absence["excused_games"]:
        parts.append(
            f"{absence['excused_games']} missade matcher räknas inte: speltidsandel "
            f"{absence['play_rate']:.2f} i stället för {absence['play_rate_without']:.2f}".replace(".", ",")
        )
    return ". ".join(parts) + "."


def gameweek_view(model: Model) -> list[dict]:
    clubs = sorted(model.fixtures)
    return [
        {
            **{k: gw[k] for k in ("number", "start", "end", "status")},
            "games_per_club": {club: model.games_in(club, gw["number"]) for club in clubs},
        }
        for gw in model.gameweeks
    ]
