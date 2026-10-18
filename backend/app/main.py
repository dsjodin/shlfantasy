"""FastAPI-app: REST-API + SSE för AI-rådgivaren + servering av frontend."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, AsyncIterator

import anthropic
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import optimizer
from .advisor import Advisor, review_prompt
from .config import get_settings
from .datastore import DataStore
from .model import Model, build_model
from .rules import COACH_CARDS, LINEUP_COMPOSITION, SQUAD_COMPOSITION
from .squad import (
    TeamState,
    alternatives,
    apply_transfers,
    best_lineup,
    card_analysis,
    evaluate_transfers,
    is_valid,
    transfer_penalty,
    validate_squad,
)
from .team_store import ProfileNotFound, TeamStore
from .views import gameweek_view, player_view

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("shlfantasy")

settings = get_settings()
store = DataStore(settings.data_dir)
teams = TeamStore(settings.data_dir)
_model_cache: dict[str, Any] = {"version": -1, "model": None}


def current_model() -> Model:
    if _model_cache["version"] != store.version or _model_cache["model"] is None:
        _model_cache["model"] = build_model(store.snapshot)
        _model_cache["version"] = store.version
    model = _model_cache["model"]
    if not model.players:
        raise HTTPException(503, "Ingen spelardata ännu – vänta på första uppdateringen eller tryck på 'Uppdatera data'.")
    return model


advisor = (
    Advisor(settings.claude_model, settings.claude_effort, lambda profile: (current_model(), teams.load(profile)))
    if settings.ai_enabled
    else None
)


async def _refresh_loop() -> None:
    while True:
        try:
            await store.refresh()
        except Exception:  # noqa: BLE001
            log.exception("Uppdatering misslyckades")
        await asyncio.sleep(settings.refresh_minutes * 60)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_refresh_loop())
    yield
    task.cancel()


app = FastAPI(title="SHL Fantasy-hjälpen", lifespan=lifespan)


# ---------------------------------------------------------------- data


@app.get("/api/status")
def status() -> dict:
    snap = store.snapshot
    model = current_model() if store.is_loaded else None
    return {
        "loaded": store.is_loaded,
        "season": snap.season,
        "fetched_at": snap.fetched_at,
        "errors": snap.errors,
        "players": len(snap.players),
        "games": len(snap.games),
        "birthdates": len(snap.birthdates),
        "next_gameweek": model.next_gameweek if model else None,
        "current_gameweek": model.current_gameweek if model else None,
        "ai_enabled": advisor is not None,
        "ai_model": settings.claude_model if advisor else None,
        "rules": {
            "squad": SQUAD_COMPOSITION,
            "lineup": LINEUP_COMPOSITION,
            "cards": COACH_CARDS,
        },
    }


@app.post("/api/refresh")
async def refresh(birthdates: bool = False) -> dict:
    await store.refresh(include_birthdates=True if birthdates else None)
    return status()


@app.get("/api/players")
def players(horizon: int = 3) -> dict:
    model = current_model()
    gws = model.horizon(horizon)
    return {
        "gameweeks": gws,
        "players": [player_view(model, p, gws) for p in model.players.values()],
    }


@app.get("/api/players/{player_id}")
def player(player_id: str, horizon: int = 4) -> dict:
    model = current_model()
    if player_id not in model.players:
        raise HTTPException(404, "Okänd spelare")
    return player_view(model, model.players[player_id], model.horizon(horizon), detailed=True)


@app.get("/api/gameweeks")
def gameweeks() -> dict:
    model = current_model()
    return {
        "next_gameweek": model.next_gameweek,
        "current_gameweek": model.current_gameweek,
        "gameweeks": gameweek_view(model),
    }


@app.get("/api/fixtures")
def fixtures(weeks: int = 6) -> dict:
    model = current_model()
    gws = model.horizon(weeks)
    return {
        "gameweeks": [model.gameweek(gw) for gw in gws],
        "clubs": {
            club: {gw: weeks_.get(gw, []) for gw in gws} for club, weeks_ in sorted(model.fixtures.items())
        },
    }


# ---------------------------------------------------------------- profiler


def profile_id(x_profile: str | None = Header(default=None)) -> str:
    """Varje familjemedlem har en egen profil. Frontend skickar vald profil i X-Profile."""
    if not x_profile or not teams.exists(x_profile):
        raise HTTPException(400, "Välj eller skapa en profil först.")
    return x_profile


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)


@app.get("/api/profiles")
def list_profiles() -> dict:
    return {"profiles": teams.profiles()}


@app.post("/api/profiles")
def create_profile(body: ProfileIn) -> dict:
    try:
        return teams.create(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/profiles/{pid}")
def rename_profile(pid: str, body: ProfileIn) -> dict:
    try:
        return teams.rename(pid, body.name)
    except ProfileNotFound as exc:
        raise HTTPException(404, "Okänd profil") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/profiles/{pid}")
def delete_profile(pid: str) -> dict:
    try:
        teams.delete(pid)
    except ProfileNotFound as exc:
        raise HTTPException(404, "Okänd profil") from exc
    return {"profiles": teams.profiles()}


Profile = Depends(profile_id)


# ---------------------------------------------------------------- mitt lag


class TeamIn(BaseModel):
    player_ids: list[str] = Field(default_factory=list, max_length=15)
    bank: float = 0.0
    free_transfers: int = Field(1, ge=0, le=2)
    used_cards: list[str] = Field(default_factory=list)


def _team_response(model: Model, state: TeamState) -> dict:
    issues = validate_squad(model, state.player_ids, state.bank)
    next_gw = model.next_gameweek
    lineup = best_lineup(model, state.player_ids, next_gw).to_dict() if next_gw and state.player_ids else None
    return {
        **state.__dict__,
        "valid": is_valid(issues),
        "issues": [i.__dict__ for i in issues],
        "squad_value": round(sum(model.players[p].price for p in state.player_ids if p in model.players), 1),
        "lineup": lineup,
    }


@app.get("/api/team")
def get_team(profile: str = Profile) -> dict:
    return _team_response(current_model(), teams.load(profile))


@app.put("/api/team")
def put_team(team: TeamIn, profile: str = Profile) -> dict:
    state = TeamState(**team.model_dump())
    state.used_cards = [c for c in state.used_cards if c in COACH_CARDS]
    teams.save(profile, state)
    return _team_response(current_model(), state)


@app.post("/api/team/validate")
def validate_team(team: TeamIn) -> dict:
    return _team_response(current_model(), TeamState(**team.model_dump()))


@app.get("/api/lineup")
def lineup(gameweek: int | None = None, profile: str = Profile) -> dict:
    model = current_model()
    gw = gameweek or model.next_gameweek
    if gw is None:
        raise HTTPException(404, "Ingen kommande matchvecka")
    return best_lineup(model, teams.load(profile).player_ids, gw).to_dict()


@app.get("/api/cards")
def cards(weeks: int = 6, profile: str = Profile) -> dict:
    model = current_model()
    return {"weeks": card_analysis(model, teams.load(profile), weeks)}


# ---------------------------------------------------------------- byten


class TransferIn(BaseModel):
    out: list[str]
    into: list[str] = Field(alias="in")
    horizon: int = Field(3, ge=1, le=10)
    free_card: bool = False


class SuggestIn(BaseModel):
    horizon: int = Field(3, ge=1, le=10)
    max_transfers: int = Field(2, ge=1, le=5)
    free_card: bool = False
    keep: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class BuildIn(BaseModel):
    horizon: int = Field(3, ge=1, le=10)
    budget: float = 100.0


@app.post("/api/transfers/evaluate")
def transfers_evaluate(body: TransferIn, profile: str = Profile) -> dict:
    return evaluate_transfers(current_model(), teams.load(profile), body.out, body.into, body.horizon, body.free_card)


@app.post("/api/transfers/apply")
def transfers_apply(body: TransferIn, profile: str = Profile) -> dict:
    """Genomför bytet i ditt sparade lag (efter att du gjort det på fantasy.shl.se)."""
    model = current_model()
    state = teams.load(profile)
    result = evaluate_transfers(model, state, body.out, body.into, body.horizon, body.free_card)
    if not result["valid"]:
        raise HTTPException(400, "; ".join(i["message"] for i in result["issues"] if i["level"] == "error"))
    used_free = 0 if body.free_card else min(state.free_transfers, len(body.out))
    state.player_ids = apply_transfers(state.player_ids, body.out, body.into)
    state.bank = result["bank_after"]
    state.free_transfers = state.free_transfers - used_free
    if body.free_card and "fria_byten" not in state.used_cards:
        state.used_cards.append("fria_byten")
    teams.save(profile, state)
    return _team_response(model, state)


@app.post("/api/transfers/suggest")
async def transfers_suggest(body: SuggestIn, profile: str = Profile) -> dict:
    model, state = current_model(), teams.load(profile)
    if not state.player_ids:
        raise HTTPException(400, "Lägg in ditt lag först.")
    options = await asyncio.to_thread(
        optimizer.suggest, model, state, body.horizon, body.max_transfers, body.free_card, set(body.keep), set(body.avoid)
    )
    return {"options": options}


@app.post("/api/transfers/build")
async def transfers_build(body: BuildIn) -> dict:
    """Bygger ett helt lag från grunden (t.ex. inför säsongen eller för Fria Byten)."""
    model = current_model()
    state = TeamState(player_ids=[], bank=body.budget, free_transfers=0)
    result = await asyncio.to_thread(optimizer.optimize, model, state, body.horizon, 15, True)
    if not result:
        raise HTTPException(400, "Hittade inget giltigt lag.")
    return result


@app.get("/api/transfers/alternatives/{player_id}")
def transfers_alternatives(
    player_id: str, horizon: int = 3, limit: int = 10, max_price: float | None = None, profile: str = Profile
) -> dict:
    model, state = current_model(), teams.load(profile)
    if player_id not in state.player_ids:
        raise HTTPException(400, "Spelaren finns inte i ditt lag.")
    return {"options": alternatives(model, state, player_id, horizon, limit, max_price)}


@app.get("/api/transfers/penalty")
def penalty(transfers: int, free_transfers: int, free_card: bool = False) -> dict:
    return {"penalty": transfer_penalty(transfers, free_transfers, free_card)}


# ---------------------------------------------------------------- AI


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class ReviewIn(BaseModel):
    out: list[str]
    into: list[str] = Field(alias="in")
    horizon: int = Field(3, ge=1, le=10)
    conversation_id: str | None = None


def _require_ai() -> Advisor:
    if advisor is None:
        raise HTTPException(503, "AI är inte aktiverat. Sätt ANTHROPIC_API_KEY i .env och starta om.")
    return advisor


async def _sse(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    except anthropic.AuthenticationError:
        yield _sse_error("Ogiltig API-nyckel för Claude. Kontrollera ANTHROPIC_API_KEY.")
    except anthropic.RateLimitError:
        yield _sse_error("För många anrop till Claude just nu. Försök igen om en stund.")
    except anthropic.APIStatusError as exc:
        log.exception("Claude API-fel")
        yield _sse_error(f"Fel från Claude API ({exc.status_code}): {exc.message}")
    except anthropic.APIConnectionError:
        yield _sse_error("Kunde inte nå Claude API. Kontrollera nätverket.")
    except HTTPException as exc:
        yield _sse_error(str(exc.detail))


def _sse_error(message: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'message': message}, ensure_ascii=False)}\n\n" + \
        f"data: {json.dumps({'type': 'done'})}\n\n"


@app.post("/api/ai/chat")
async def ai_chat(body: ChatIn, profile: str = Profile) -> StreamingResponse:
    ai = _require_ai()
    current_model()
    return StreamingResponse(_sse(ai.chat(profile, body.conversation_id, body.message)), media_type="text/event-stream")


@app.post("/api/ai/review")
async def ai_review(body: ReviewIn, profile: str = Profile) -> StreamingResponse:
    ai = _require_ai()
    model, state = current_model(), teams.load(profile)
    if not body.out or len(body.out) != len(body.into) or any(pid not in model.players for pid in body.out + body.into):
        raise HTTPException(400, "Ogiltigt byte.")
    if any(pid not in state.player_ids for pid in body.out):
        raise HTTPException(400, "Spelaren som ska säljas finns inte i ditt lag.")
    prompt = review_prompt(model, state, body.out, body.into, body.horizon)
    return StreamingResponse(_sse(ai.chat(profile, body.conversation_id, prompt)), media_type="text/event-stream")


# ---------------------------------------------------------------- frontend

if settings.static_dir and settings.static_dir.exists():
    app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (settings.static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(settings.static_dir):
            return FileResponse(candidate)
        return FileResponse(settings.static_dir / "index.html")
