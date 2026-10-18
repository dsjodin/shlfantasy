import json

import pytest

from app.advisor import TOOLS, Toolbox, ToolError, review_prompt


def test_tool_schemas_are_serialisable():
    names = {t["name"] for t in TOOLS}
    assert {"get_my_team", "evaluate_transfers", "suggest_transfers", "coach_cards"} <= names
    evaluate = next(t for t in TOOLS if t["name"] == "evaluate_transfers")
    assert "in" in evaluate["input_schema"]["properties"]
    json.dumps(TOOLS)


def test_resolve_by_name_and_ambiguity(model, state):
    box = Toolbox(model, state)
    some = model.players[state.player_ids[0]]
    assert box.resolve(some.name) is some
    assert box.resolve(some.id) is some
    with pytest.raises(ToolError):
        box.resolve("finns inte")
    in_team = {model.players[pid].club + " " + model.players[pid].position for pid in state.player_ids}
    query = next(f"{c} D" for c in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF") if f"{c} D" not in in_team)
    with pytest.raises(ToolError):
        box.resolve(query)  # flera träffar, ingen i laget


def test_evaluate_tool_accepts_names(model, state):
    box = Toolbox(model, state)
    out = model.players[state.player_ids[-1]]
    candidate = next(
        p for p in model.players.values() if p.position == out.position and p.id not in state.player_ids
    )
    result = box.run("evaluate_transfers", {"out": [out.name], "in": [candidate.id]})
    assert result["out"][0]["name"] == out.name
    assert "net_gain" in result


def test_invalid_tool_input_raises(model, state):
    with pytest.raises(ToolError):
        Toolbox(model, state).run("search_players", {"limit": 500})


def test_tools_without_team(model):
    from app.squad import TeamState

    with pytest.raises(ToolError):
        Toolbox(model, TeamState()).run("get_my_team", {})
    assert Toolbox(model, TeamState()).run("search_players", {"position": "GK", "limit": 3})["players"]


def test_review_prompt_contains_analysis(model, state):
    out = state.player_ids[-1]
    cand = next(p.id for p in model.players.values() if p.position == model.players[out].position and p.id not in state.player_ids)
    text = review_prompt(model, state, [out], [cand], 2)
    assert model.players[out].name in text
    assert "Kalkylatorns analys" in text
