"""Prognosarkiv, automatisk viktjustering och AI-minne."""

from types import SimpleNamespace

import pytest

from app import tuning
from app.advisor import Toolbox, ToolError
from app.archive import PredictionArchive
from app.backtest import evaluate_archived
from app.memory import ProfileMemory, transfer_outcomes
from app.model import build_model
from app.projection import DEFAULT_PARAMS, Params
from app.squad import TeamState, evaluate_transfers
from app.team_store import TeamStore

from .conftest import cheapest_valid_squad, make_snapshot


# ---------------------------------------------------------------- arkiv


def test_archive_records_next_week_and_freezes(tmp_path):
    snap = make_snapshot()
    archive = PredictionArchive(tmp_path)
    assert archive.record(build_model(snap)) == 2
    saved = archive.load(2)
    some_id = snap.players[0]["id"]
    assert saved["players"][some_id]["price"] == snap.players[0]["price"]

    # Vecka 2 startar: prisändringar efter det får inte skriva över vecka 2:s prognos
    snap.gameweeks[1]["status"] = "ongoing"
    snap.players[0]["price"] = 99.0
    assert archive.record(build_model(snap)) == 3
    assert archive.load(2)["players"][some_id]["price"] != 99.0
    assert archive.weeks() == [2, 3]


def test_evaluate_archived_uses_saved_predictions(tmp_path):
    snap = make_snapshot()
    archive = PredictionArchive(tmp_path)
    archive.record(build_model(snap))
    snap.gameweeks[1]["status"] = "completed"
    snap.gameweek_points = {"2": {p["id"]: {"games": 1, "points": 3} for p in snap.players}}
    weeks, result = evaluate_archived(snap, archive)
    assert weeks == [2]
    assert result["samples"] == len(snap.players)


# ---------------------------------------------------------------- viktjustering


def _fake_weeks(n):
    return [SimpleNamespace(number=i + 2, archived_prices=False) for i in range(n)]


def _patch(monkeypatch, n_weeks, current_mae, candidate_mae, current_lineup=0.4, candidate_lineup=0.4):
    candidate = Params(prior_strength=2.0, form_weight=0.5)
    monkeypatch.setattr(tuning, "build_weeks", lambda snap, archive=None: _fake_weeks(n_weeks))
    monkeypatch.setattr(tuning, "grid_search", lambda weeks, grid: (candidate, {}))

    def fake_eval(weeks, params):
        if params == candidate:
            return {"mae": candidate_mae, "lineup_efficiency": candidate_lineup}
        return {"mae": current_mae, "lineup_efficiency": current_lineup}

    monkeypatch.setattr(tuning, "evaluate", fake_eval)
    return candidate


def test_tuning_waits_for_enough_weeks(tmp_path, monkeypatch):
    _patch(monkeypatch, n_weeks=3, current_mae=5.0, candidate_mae=4.0)
    store = tuning.ParamStore(tmp_path)
    entry = store.maybe_tune(None)
    assert entry["adopted"] is False and "För få" in entry["reason"]
    assert store.current() == DEFAULT_PARAMS
    assert store.maybe_tune(None) is None  # samma vecka prövas bara en gång


def test_tuning_adopts_clear_improvement(tmp_path, monkeypatch):
    candidate = _patch(monkeypatch, n_weeks=5, current_mae=5.0, candidate_mae=4.8)
    store = tuning.ParamStore(tmp_path)
    entry = store.maybe_tune(None)
    assert entry["adopted"] is True
    assert entry["holdout_weeks"] == [5, 6]
    assert store.current() == candidate
    assert store.version == 1
    assert store.log()[0]["week"] == 6


def test_tuning_rejects_small_or_lineup_worse(tmp_path, monkeypatch):
    _patch(monkeypatch, n_weeks=5, current_mae=5.0, candidate_mae=4.98)
    store = tuning.ParamStore(tmp_path)
    assert store.maybe_tune(None)["adopted"] is False
    assert store.current() == DEFAULT_PARAMS

    _patch(monkeypatch, n_weeks=6, current_mae=5.0, candidate_mae=4.5, current_lineup=0.5, candidate_lineup=0.4)
    entry = store.maybe_tune(None)
    assert entry["adopted"] is False and "elva" in entry["reason"]


# ---------------------------------------------------------------- minne


@pytest.fixture
def memory(tmp_path):
    store = TeamStore(tmp_path)
    return ProfileMemory(store, store.create("Anna")["id"])


def test_notes(memory):
    note = memory.add_note("  Vill   inte ha två målvakter från samma lag ")
    assert note["text"] == "Vill inte ha två målvakter från samma lag"
    assert memory.notes() == [note]
    assert memory.delete_note(note["id"]) is True
    assert memory.delete_note(note["id"]) is False
    with pytest.raises(ValueError):
        memory.add_note("   ")


def test_transfer_log_and_outcome(memory, snapshot):
    model = build_model(snapshot)
    state = TeamState(cheapest_valid_squad(model), bank=5.0, free_transfers=1)
    out = state.player_ids[-1]
    new = next(p.id for p in model.players.values() if p.position == model.players[out].position and p.id not in state.player_ids)
    ev = evaluate_transfers(model, state, [out], [new], 2)
    memory.log_transfer(model, [out], [new], ev)
    [logged] = memory.transfers()
    assert logged["gameweek"] == 2 and logged["out"][0]["id"] == out

    # Inga spelade veckor ännu -> inget utfall
    assert transfer_outcomes(model, memory.transfers())[0]["net_points"] is None

    # Vecka 2 spelad: köpt spelare tog 10 p, såld 4 p
    snapshot.gameweeks[1]["status"] = "completed"
    snapshot.gameweek_points = {"2": {new: {"games": 1, "points": 10}, out: {"games": 1, "points": 4}}}
    [outcome] = transfer_outcomes(build_model(snapshot), memory.transfers())
    assert (outcome["in_points"], outcome["out_points"], outcome["net_points"]) == (10, 4, 6)


def test_memory_tools(memory, model, state):
    box = Toolbox(model, state, memory)
    saved = box.run("remember", {"note": "Sparar Fria Byten till jul"})["saved"]
    data = box.run("get_memory", {})
    assert data["notes"][0]["text"] == "Sparar Fria Byten till jul"
    assert data["summary"]["transfers"] == 0
    box.run("forget", {"note_id": saved["id"]})
    with pytest.raises(ToolError):
        box.run("forget", {"note_id": saved["id"]})
    with pytest.raises(ToolError):
        Toolbox(model, state).run("get_memory", {})
