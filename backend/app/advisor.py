"""AI-rådgivare: Claude med verktyg som räknar på riktig data.

Claude får aldrig gissa siffror – alla priser, budgetar och förväntade poäng hämtas via
verktyg som använder samma regelmotor som resten av appen.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from datetime import date
from typing import Any, AsyncIterator, Callable, Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

from . import optimizer
from .memory import ProfileMemory, transfer_outcomes
from .model import Model, Player
from .rules import RULES_TEXT
from .squad import (
    TeamState,
    alternatives,
    best_lineup,
    card_analysis,
    evaluate_transfers,
    validate_squad,
)
from .views import compact_player, player_view

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 12
MAX_CONVERSATIONS = 30
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = f"""\
Du är en skarp och ärlig rådgivare för Fantasy SHL (svensk ishockey). Användaren vill ha hjälp att
välja byten, kapten och coachkort – och vill att du ifrågasätter deras val när det finns bättre
alternativ. Svara alltid på svenska, kort och konkret.

Så arbetar du:
- Räkna aldrig i huvudet på priser, budget, lagbegränsningar eller förväntade poäng. Använd verktygen;
  de använder spelets regler och aktuell data. Hämta användarens lag med get_my_team innan du ger råd om det.
- När användaren föreslår ett byte: kontrollera det med evaluate_transfers och leta efter bättre
  alternativ med find_replacements och/eller suggest_transfers. Om något är tydligt bättre, säg det rakt ut
  och förklara varför (fler matcher, bättre form, billigare så att budget frigörs, skaderisk, osv.).
  Om användarens val är bra, bekräfta det och säg varför.
- Ta hänsyn till poängavdraget (−10 p) för byten utöver de gratis, och till att sparade byten har ett värde.
- xP (förväntade poäng) kommer från en enkel statistisk modell: poäng per match krympt mot prisets
  förväntan, andel spelade lagmatcher, form och antal matcher per vecka. Den vet inget om kedjor,
  powerplay-roller, målvaktsrotation eller nyheter. Lyft sådana osäkerheter när de spelar roll och
  föreslå vad användaren bör kontrollera.
- Positioner: GK = målvakt, D = back, C = center, F = forward (ytter). Statusen "unavailable" betyder
  att spelaren missade senaste matchen; "injured" betyder skadad.
- Presentera konkreta förslag som "UT: Namn (lag, pris) → IN: Namn (lag, pris)" med förväntad
  poängvinst och vad som händer med banken.

Minne (per användare):
- Hämta get_memory innan du ger råd om byten, kapten eller strategi. Där finns användarens sparade
  preferenser och tidigare byten med faktiskt utfall.
- Använd historiken för att lära av utfallet: om användaren upprepar ett mönster som tidigare slagit fel
  (t.ex. köpt spelare på formtopp som sedan dalat), säg det. Ett enskilt byte är dock mest slump – peka
  på mönster, inte enstaka utfall.
- Spara med remember när användaren uttrycker en bestående preferens, regel eller plan ("jag vill alltid
  ha två målvakter från olika lag", "jag sparar Fria Byten till jul"). Spara inte tillfälliga frågor,
  statistik eller sådant som redan finns i appen. Säg kort att du sparat det.
- Ta bort en anteckning med forget om användaren ber om det eller om den uppenbart inte gäller längre.

Spelets regler:
{RULES_TEXT}"""

WEB_SEARCH_PROMPT = """
Webbsökning:
- Du kan söka på webben. Använd det för sådant verktygen inte vet: skador, sjukdom, avstängningar,
  laguppställningar, kedjor och powerplay-roller, vilken målvakt som startar, trejder och nyheter.
- Sök framför allt när du är på väg att rekommendera en spelare (köp, kapten) eller när en spelare i
  laget har status injured/unavailable. Sök inte efter statistik som verktygen redan har.
- Svenska källor brukar vara bäst (shl.se, lagens sajter, hockeysverige.se, expressen.se, aftonbladet.se,
  svenska dagstidningar). Kontrollera datum – gamla nyheter kan vara inaktuella.
- Säg tydligt vad som kommer från nyheter och vad som kommer från statistiken."""

WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 5,
    "user_location": {"type": "approximate", "country": "SE", "timezone": "Europe/Stockholm"},
}


# ---------------------------------------------------------------- verktyg


class NoInput(BaseModel):
    pass


class SearchPlayersInput(BaseModel):
    position: Literal["GK", "D", "C", "F"] | None = None
    club: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    include_unavailable: bool = False
    sort_by: Literal["xp_next", "xp_horizon", "form", "ppg", "total_points", "price", "value"] = "xp_horizon"
    horizon: int = Field(3, ge=1, le=8)
    limit: int = Field(15, ge=1, le=40)


class GetPlayerInput(BaseModel):
    player: str


class EvaluateTransfersInput(BaseModel):
    out: list[str]
    into: list[str] = Field(alias="in")
    horizon: int = Field(3, ge=1, le=8)
    free_card: bool = False


class SuggestTransfersInput(BaseModel):
    max_transfers: int = Field(2, ge=1, le=4)
    horizon: int = Field(3, ge=1, le=8)
    free_card: bool = False
    keep: list[str] = []
    avoid: list[str] = []


class FindReplacementsInput(BaseModel):
    out: str
    horizon: int = Field(3, ge=1, le=8)
    max_price: float | None = None
    limit: int = Field(8, ge=1, le=20)


class FixturesInput(BaseModel):
    weeks: int = Field(4, ge=1, le=10)


class CoachCardsInput(BaseModel):
    weeks: int = Field(6, ge=1, le=12)


class RememberInput(BaseModel):
    note: str = Field(min_length=1, max_length=300)


class ForgetInput(BaseModel):
    note_id: str


def _schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema(by_alias=True)
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


TOOL_SPECS: list[tuple[str, str, type[BaseModel]]] = [
    (
        "get_my_team",
        "Hämtar användarens nuvarande trupp (15 spelare) med pris, status, xP, bank, antal gratis byten, "
        "använda coachkort, regelkontroll och föreslagen laguttagning/kapten för nästa matchvecka.",
        NoInput,
    ),
    (
        "search_players",
        "Söker bland alla spelare med filter och sortering. sort_by='value' sorterar på xP per Mkr. "
        "Returnerar kompakt statistik inkl. xp_next (nästa vecka) och xp_horizon (summa över horizon veckor).",
        SearchPlayersInput,
    ),
    (
        "get_player",
        "Detaljer för en spelare (namn eller id): poängfördelning, poäng per matchvecka, kommande matcher.",
        GetPlayerInput,
    ),
    (
        "evaluate_transfers",
        "Räknar på ett eller flera byten mot användarens lag: regelkontroll (budget, positioner, max 3 per lag), "
        "bank efter byte, poängavdrag och förändring i förväntade poäng. 'out' och 'in' är listor med namn eller id "
        "i samma ordning (out[0] ersätts av in[0]). free_card=true simulerar coachkortet Fria Byten.",
        EvaluateTransfersInput,
    ),
    (
        "suggest_transfers",
        "Optimerar fram bästa möjliga byten (1..max_transfers) givet budget, regler och poängavdrag. "
        "keep = spelare som inte får säljas, avoid = spelare som inte får köpas. free_card=true ger obegränsat "
        "antal byten utan avdrag (Fria Byten). Kan ta några sekunder.",
        SuggestTransfersInput,
    ),
    (
        "find_replacements",
        "Listar de bästa ersättarna för en viss spelare i användarens lag (samma position, inom budget och "
        "lagbegränsning), rangordnade efter förväntad poängvinst för truppen.",
        FindReplacementsInput,
    ),
    (
        "get_fixtures",
        "Antal matcher och motstånd per lag för de kommande matchveckorna. Bra för kapten och coachkort.",
        FixturesInput,
    ),
    (
        "coach_cards",
        "Beräknar förväntad extra poäng för varje coachkort (Toppa Laget, Anfall, Försvar, Juniorer, Veteraner) "
        "per kommande matchvecka med användarens nuvarande trupp, och vilka kort som redan är använda.",
        CoachCardsInput,
    ),
    (
        "get_memory",
        "Hämtar användarens sparade anteckningar (preferenser, regler, planer) och historik över byten som "
        "gjorts i appen, med faktiskt utfall: poäng för köpta minus sålda spelare sedan bytet, minus avdrag.",
        NoInput,
    ),
    (
        "remember",
        "Sparar en kort anteckning om användarens bestående preferens, regel eller plan till framtida samtal.",
        RememberInput,
    ),
    (
        "forget",
        "Tar bort en sparad anteckning (id från get_memory).",
        ForgetInput,
    ),
]

TOOLS = [
    {"name": name, "description": desc, "input_schema": _schema(model), "eager_input_streaming": True}
    for name, desc, model in TOOL_SPECS
]
TOOL_MODELS = {name: model for name, _, model in TOOL_SPECS}

TOOL_LABELS = {
    "get_my_team": "Hämtar ditt lag",
    "search_players": "Söker spelare",
    "get_player": "Hämtar spelardetaljer",
    "evaluate_transfers": "Räknar på byte",
    "suggest_transfers": "Optimerar byten",
    "find_replacements": "Letar ersättare",
    "get_fixtures": "Kollar matchschemat",
    "coach_cards": "Analyserar coachkort",
    "get_memory": "Läser minnet",
    "remember": "Sparar i minnet",
    "forget": "Glömmer anteckning",
}


class ToolError(Exception):
    pass


class Toolbox:
    def __init__(self, model: Model, state: TeamState, memory: ProfileMemory | None = None):
        self.model = model
        self.state = state
        self.memory = memory

    def resolve(self, query: str) -> Player:
        matches = self.model.find(query)
        if not matches:
            raise ToolError(f"Hittade ingen spelare som matchar '{query}'.")
        if len(matches) > 1:
            in_team = [p for p in matches if p.id in self.state.player_ids]
            if len(in_team) == 1:
                return in_team[0]
            options = ", ".join(f"{p.name} ({p.club}, {p.position}, id {p.id})" for p in matches[:8])
            raise ToolError(f"'{query}' är tvetydigt: {options}. Använd id.")
        return matches[0]

    def run(self, name: str, raw_input: Any) -> Any:
        model_cls = TOOL_MODELS.get(name)
        if model_cls is None:
            raise ToolError(f"Okänt verktyg: {name}")
        try:
            args = model_cls.model_validate(raw_input or {})
        except ValidationError as exc:
            raise ToolError(f"Ogiltig indata: {exc.errors(include_url=False)}") from exc
        return getattr(self, f"tool_{name}")(args)

    def _require_team(self) -> None:
        if not self.state.player_ids:
            raise ToolError("Användaren har inte lagt in något lag ännu. Be dem lägga in sitt lag under 'Mitt lag'.")

    def tool_get_my_team(self, _: NoInput) -> dict:
        self._require_team()
        gws = self.model.horizon(3)
        next_gw = self.model.next_gameweek
        lineup = best_lineup(self.model, self.state.player_ids, next_gw).to_dict() if next_gw else None
        return {
            "next_gameweek": next_gw,
            "horizon_gameweeks": gws,
            "bank": self.state.bank,
            "free_transfers": self.state.free_transfers,
            "used_cards": self.state.used_cards,
            "squad": [
                compact_player(self.model, self.model.players[pid], gws)
                for pid in self.state.player_ids
                if pid in self.model.players
            ],
            "squad_value": round(sum(self.model.players[pid].price for pid in self.state.player_ids if pid in self.model.players), 1),
            "issues": [i.__dict__ for i in validate_squad(self.model, self.state.player_ids, self.state.bank)],
            "suggested_lineup": lineup,
        }

    def tool_search_players(self, a: SearchPlayersInput) -> dict:
        gws = self.model.horizon(a.horizon)
        players = list(self.model.players.values())
        if a.position:
            players = [p for p in players if p.position == a.position]
        if a.club:
            players = [p for p in players if p.club.lower() == a.club.lower()]
        if a.min_price is not None:
            players = [p for p in players if p.price >= a.min_price]
        if a.max_price is not None:
            players = [p for p in players if p.price <= a.max_price]
        if not a.include_unavailable:
            players = [p for p in players if p.status == "active"]
        next_gw = gws[0] if gws else None
        keys = {
            "xp_next": lambda p: p.xp.get(next_gw, 0.0),
            "xp_horizon": lambda p: p.xp_over(gws),
            "form": lambda p: p.form,
            "ppg": lambda p: p.ppg,
            "total_points": lambda p: p.total_points,
            "price": lambda p: p.price,
            "value": lambda p: p.xp_over(gws) / p.price if p.price else 0,
        }
        players.sort(key=keys[a.sort_by], reverse=True)
        return {
            "gameweeks": gws,
            "count": len(players),
            "players": [
                {**compact_player(self.model, p, gws), "in_my_team": p.id in self.state.player_ids}
                for p in players[: a.limit]
            ],
        }

    def tool_get_player(self, a: GetPlayerInput) -> dict:
        p = self.resolve(a.player)
        view = player_view(self.model, p, self.model.horizon(4), detailed=True)
        view["in_my_team"] = p.id in self.state.player_ids
        return view

    def tool_evaluate_transfers(self, a: EvaluateTransfersInput) -> dict:
        self._require_team()
        out_ids = [self.resolve(q).id for q in a.out]
        in_ids = [self.resolve(q).id for q in a.into]
        result = evaluate_transfers(self.model, self.state, out_ids, in_ids, a.horizon, a.free_card)
        return self._named_transfer(result, out_ids, in_ids)

    def tool_suggest_transfers(self, a: SuggestTransfersInput) -> dict:
        self._require_team()
        keep = {self.resolve(q).id for q in a.keep}
        avoid = {self.resolve(q).id for q in a.avoid}
        options = optimizer.suggest(self.model, self.state, a.horizon, a.max_transfers, a.free_card, keep, avoid)
        return {
            "options": [self._named_transfer(o, o["out"], o["in"]) for o in options[:4]],
            "note": "net_gain = förväntad poängvinst över perioden minus poängavdrag.",
        }

    def tool_find_replacements(self, a: FindReplacementsInput) -> dict:
        self._require_team()
        out = self.resolve(a.out)
        if out.id not in self.state.player_ids:
            raise ToolError(f"{out.name} finns inte i användarens lag.")
        gws = self.model.horizon(a.horizon)
        options = alternatives(self.model, self.state, out.id, a.horizon, a.limit, a.max_price)
        return {
            "out": compact_player(self.model, out, gws),
            "bank": self.state.bank,
            "replacements": [
                {**compact_player(self.model, self.model.players[o["player_id"]], gws), "squad_xp_gain": o["xp_gain"], "bank_after": o["bank_after"]}
                for o in options
            ],
        }

    def tool_get_fixtures(self, a: FixturesInput) -> dict:
        gws = self.model.horizon(a.weeks)
        return {
            "gameweeks": [
                {"number": gw, "start": self.model.gameweek(gw)["start"], "end": self.model.gameweek(gw)["end"]}
                for gw in gws
            ],
            "clubs": {
                club: {
                    gw: [f"{'H' if f['home'] else 'B'} {f['opponent']}" for f in weeks.get(gw, [])]
                    for gw in gws
                }
                for club, weeks in sorted(self.model.fixtures.items())
            },
        }

    def tool_coach_cards(self, a: CoachCardsInput) -> dict:
        self._require_team()
        return {"used_cards": self.state.used_cards, "weeks": card_analysis(self.model, self.state, a.weeks)}

    def _require_memory(self) -> ProfileMemory:
        if self.memory is None:
            raise ToolError("Minnet är inte tillgängligt.")
        return self.memory

    def tool_get_memory(self, _: NoInput) -> dict:
        memory = self._require_memory()
        outcomes = transfer_outcomes(self.model, memory.transfers())
        settled = [t for t in outcomes if t["net_points"] is not None]
        return {
            "notes": memory.notes(),
            "transfers": [
                {
                    "gameweek": t["gameweek"],
                    "out": [f"{p['name']} ({p['club']}, {p['price']})" for p in t["out"]],
                    "in": [f"{p['name']} ({p['club']}, {p['price']})" for p in t["in"]],
                    "expected_gain": t.get("expected_gain"),
                    "penalty": t.get("penalty", 0),
                    "weeks_played": t["weeks_played"],
                    "in_points": t["in_points"],
                    "out_points": t["out_points"],
                    "net_points": t["net_points"],
                }
                for t in outcomes[-20:]
            ],
            "summary": {
                "transfers": len(outcomes),
                "settled": len(settled),
                "net_points_total": sum(t["net_points"] for t in settled),
            },
        }

    def tool_remember(self, a: RememberInput) -> dict:
        try:
            note = self._require_memory().add_note(a.note)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return {"saved": note}

    def tool_forget(self, a: ForgetInput) -> dict:
        if not self._require_memory().delete_note(a.note_id):
            raise ToolError(f"Ingen anteckning med id {a.note_id}.")
        return {"deleted": a.note_id}

    def _named_transfer(self, result: dict, out_ids: list[str], in_ids: list[str]) -> dict:
        gws = result.get("gameweeks", [])
        summary = {k: v for k, v in result.items() if k not in ("new_player_ids", "out", "in")}
        summary["out"] = [compact_player(self.model, self.model.players[i], gws) for i in out_ids]
        summary["in"] = [compact_player(self.model, self.model.players[i], gws) for i in in_ids]
        return summary


# ---------------------------------------------------------------- konversation


class Advisor:
    def __init__(
        self,
        model_id: str,
        effort: str,
        context: Callable[[str], tuple[Model, TeamState, ProfileMemory | None]],
        web_search: bool = True,
    ):
        self.client = anthropic.AsyncAnthropic()
        self.model_id = model_id
        self.effort = effort
        self.context = context
        # Systemprompt och verktyg bestäms en gång så att prompt-cachen träffar
        self.system = SYSTEM_PROMPT + (WEB_SEARCH_PROMPT if web_search else "")
        self.tools = TOOLS + ([WEB_SEARCH_TOOL] if web_search else [])
        # {conversation_id: (profil, meddelanden)} – en profil kan inte fortsätta någon annans konversation
        self.conversations: OrderedDict[str, tuple[str, list[dict[str, Any]]]] = OrderedDict()

    def _conversation(self, profile: str, conversation_id: str | None) -> tuple[str, list[dict[str, Any]]]:
        if conversation_id and conversation_id in self.conversations:
            owner, messages = self.conversations[conversation_id]
            if owner == profile:
                self.conversations.move_to_end(conversation_id)
                return conversation_id, messages
        cid = uuid.uuid4().hex
        self.conversations[cid] = (profile, [])
        while len(self.conversations) > MAX_CONVERSATIONS:
            self.conversations.popitem(last=False)
        return cid, self.conversations[cid][1]

    async def chat(self, profile: str, conversation_id: str | None, text: str) -> AsyncIterator[dict[str, Any]]:
        cid, messages = self._conversation(profile, conversation_id)
        yield {"type": "conversation", "id": cid}

        model, _, _ = self.context(profile)
        next_gw = model.next_gameweek
        gw = model.gameweek(next_gw) if next_gw else None
        when = f"nästa matchvecka är {next_gw} ({gw['start']} – {gw['end']})" if gw else "ingen kommande matchvecka"
        messages.append({"role": "user", "content": f"[Idag {date.today().isoformat()}, {when}]\n\n{text}"})

        for _ in range(MAX_TOOL_ROUNDS):
            final = None
            for attempt in range(3):
                try:
                    async with self.client.beta.messages.stream(
                        model=self.model_id,
                        max_tokens=64000,
                        system=self.system,
                        tools=self.tools,
                        messages=messages,
                        thinking={"type": "adaptive"},
                        output_config={"effort": self.effort},
                        cache_control={"type": "ephemeral"},
                        betas=[FALLBACK_BETA],
                        fallbacks="default",
                    ) as stream:
                        async for event in stream:
                            if event.type == "text":
                                yield {"type": "text", "text": event.text}
                            elif event.type == "content_block_start" and event.content_block.type == "server_tool_use":
                                yield {"type": "tool", "name": "web_search", "label": "Söker på webben"}
                        final = await stream.get_final_message()
                    break
                except ValueError:
                    # Verktygsindata som inte gick att tolka alls – försök igen med samma historik.
                    if attempt == 2:
                        raise
                    yield {"type": "text", "text": "\n"}

            messages.append({"role": "assistant", "content": final.content})
            tool_uses = [b for b in final.content if b.type == "tool_use"]
            sources = _sources(final.content)
            if sources:
                yield {"type": "sources", "sources": sources}

            if final.stop_reason == "pause_turn":
                # Webbsökningen nådde serverns gräns per anrop – skicka tillbaka så fortsätter den
                continue
            if final.stop_reason == "refusal":
                self._close_open_tools(messages, tool_uses, "Svaret avbröts.")
                yield {"type": "error", "message": "Modellen avböjde att svara på den frågan."}
                break
            if not tool_uses:
                break
            if final.stop_reason == "max_tokens":
                self._close_open_tools(messages, tool_uses, "Svaret blev för långt och avbröts.")
                yield {"type": "error", "message": "Svaret blev för långt och avbröts."}
                break

            model, state, memory = self.context(profile)
            toolbox = Toolbox(model, state, memory)
            results = []
            for block in tool_uses:
                yield {"type": "tool", "name": block.name, "label": TOOL_LABELS.get(block.name, block.name)}
                try:
                    output = toolbox.run(block.name, block.input)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, ensure_ascii=False)}
                    )
                except ToolError as exc:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True})
                except Exception as exc:  # noqa: BLE001 - verktygsfel ska inte döda konversationen
                    log.exception("Verktyget %s kraschade", block.name)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": f"Internt fel: {exc}", "is_error": True}
                    )
            messages.append({"role": "user", "content": results})
        else:
            yield {"type": "error", "message": "För många verktygsanrop – avbryter."}

        yield {"type": "done"}

    @staticmethod
    def _close_open_tools(messages: list[dict[str, Any]], tool_uses: list[Any], reason: str) -> None:
        """Varje tool_use måste ha ett svar, annars avvisas nästa fråga i samma konversation."""
        if tool_uses:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": b.id, "content": reason, "is_error": True}
                        for b in tool_uses
                    ],
                }
            )


def _sources(content: list[Any]) -> list[dict[str, str]]:
    """Webbkällor som Claude citerat i svaret."""
    seen: dict[str, str] = {}
    for block in content:
        for citation in getattr(block, "citations", None) or []:
            url = getattr(citation, "url", None)
            if url and url not in seen:
                seen[url] = getattr(citation, "title", None) or url
    return [{"url": url, "title": title} for url, title in seen.items()]


def review_prompt(model: Model, state: TeamState, out_ids: list[str], in_ids: list[str], horizon: int) -> str:
    """Bygger en granskningsfråga med kalkylatorns resultat och modellens bästa alternativ."""
    toolbox = Toolbox(model, state)
    evaluation = toolbox._named_transfer(
        evaluate_transfers(model, state, out_ids, in_ids, horizon), out_ids, in_ids
    )
    alts = {}
    for pid in out_ids:
        options = alternatives(model, state, pid, horizon, limit=5)
        gws = model.horizon(horizon)
        alts[model.players[pid].name] = [
            {**compact_player(model, model.players[o["player_id"]], gws), "squad_xp_gain": o["xp_gain"]}
            for o in options
        ]
    lines = [
        f"{model.players[o].name} ({model.players[o].club}, {model.players[o].price} Mkr) → "
        f"{model.players[i].name} ({model.players[i].club}, {model.players[i].price} Mkr)"
        for o, i in zip(out_ids, in_ids)
    ]
    return (
        "Jag funderar på följande byte:\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\n\nGranska mitt val kritiskt. Är det värt det, eller finns det bättre alternativ? "
        "Ta hänsyn till poängavdrag, matchschema, form och budget. Avsluta med en tydlig rekommendation.\n\n"
        f"Kalkylatorns analys:\n{json.dumps(evaluation, ensure_ascii=False)}\n\n"
        f"Modellens bästa ersättare per utgående spelare:\n{json.dumps(alts, ensure_ascii=False)}"
    )
