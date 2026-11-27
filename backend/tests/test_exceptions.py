"""Manuella frånvaroundantag (app/exceptions.py): privat/vila sänker inte speltidsandelen,
skada/avstängning gör det som förut, återkomstdatum styr kommande veckor."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from app import exceptions as exc
from app.backtest import build_weeks
from app.model import build_model
from app.trend import recent_play_rate

from .conftest import make_snapshot

# I testdatan spelar AAA fyra matcher vecka 1 (2, 3, 5 och 6 september), tre matcher
# vecka 2 (9, 10 och 12 september) och en vecka 3 (16 september).


def _snapshot_with_missed_game():
    """AAA:s första back har missat en av lagets fyra matcher vecka 1."""
    snap = make_snapshot()
    player = next(p for p in snap.players if p["club"] == "AAA" and p["position"] == "D")
    player["games_played"] = 3
    player["total_points"] = 12
    player["ppg"] = 4.0
    snap.gameweek_points = {
        "1": {
            p["id"]: {"games": p["games_played"], "points": p["total_points"], "pm": 0, "cats": {}}
            for p in snap.players
        }
    }
    return snap, player["id"]


def _absence(pid, reason, start, end=None, ret=None):
    rows, errors = exc.parse([{"player_id": pid, "reason": reason, "from": start, "to": end, "expected_return": ret}])
    assert not errors
    return rows


def test_private_absence_does_not_lower_play_rate():
    snap, pid = _snapshot_with_missed_game()
    without = build_model(snap).players[pid]
    with_exc = build_model(snap, absences=_absence(pid, "privat", "2026-09-03")).players[pid]

    assert without.play_rate == pytest.approx(0.75)  # 3 av 4 matcher
    assert with_exc.play_rate == pytest.approx(1.0)  # den missade matchen räknas inte
    assert with_exc.xp_per_game > without.xp_per_game
    assert with_exc.absence["excused_games"] == 1
    assert with_exc.absence["play_rate_without"] == pytest.approx(0.75)
    assert with_exc.absence["absences"][0]["reason"] == "privat"


def test_rest_counts_like_private():
    snap, pid = _snapshot_with_missed_game()
    rested = build_model(snap, absences=_absence(pid, "vila", "2026-09-03")).players[pid]
    assert rested.play_rate == pytest.approx(1.0)


def test_injury_lowers_play_rate_as_before_but_is_shown():
    snap, pid = _snapshot_with_missed_game()
    without = build_model(snap).players[pid]
    injured = build_model(snap, absences=_absence(pid, "skada", "2026-09-03")).players[pid]
    assert injured.play_rate == pytest.approx(without.play_rate)
    assert injured.xp_per_game == pytest.approx(without.xp_per_game)
    assert injured.absence["excused_games"] == 0
    assert injured.absence["absences"][0]["reason"] == "skada"


def test_player_who_played_anyway_never_gets_rate_above_one():
    snap = make_snapshot()
    pid = snap.players[0]["id"]  # spelade alla fyra matcherna
    snap.gameweek_points = {"1": {p["id"]: {"games": 4, "points": 16, "pm": 0, "cats": {}} for p in snap.players}}
    p = build_model(snap, absences=_absence(pid, "privat", "2026-09-02", "2026-09-06")).players[pid]
    assert p.play_rate <= 1.0
    assert p.absence["excused_games"] == 0


def test_expected_return_sets_upcoming_availability():
    snap, pid = _snapshot_with_missed_game()
    next(p for p in snap.players if p["id"] == pid)["status"] = "injured"
    active = build_model(make_snapshot_active(snap, pid)).players[pid]
    # Skadad, väntas tillbaka 11 september: missar 9 och 10, spelar 12 (1 av 3) och vecka 3
    p = build_model(snap, absences=_absence(pid, "skada", "2026-09-08", ret="2026-09-11")).players[pid]
    assert p.xp[2] == pytest.approx(active.xp[2] / 3, abs=0.02)
    assert p.xp[3] == pytest.approx(active.xp[3], abs=0.02)
    assert p.absence["overrides_status"] is True


def test_injury_without_return_keeps_status_ramp():
    snap, pid = _snapshot_with_missed_game()
    next(p for p in snap.players if p["id"] == pid)["status"] = "injured"
    p = build_model(snap, absences=_absence(pid, "skada", "2026-09-06")).players[pid]
    assert p.xp[2] == 0.0  # statusens nedtrappning gäller fortfarande
    assert p.absence["overrides_status"] is False


def test_private_absence_in_upcoming_week_zeroes_those_games():
    snap, pid = _snapshot_with_missed_game()
    base = build_model(snap).players[pid]
    p = build_model(snap, absences=_absence(pid, "privat", "2026-09-09", "2026-09-10")).players[pid]
    assert p.xp[2] == pytest.approx(base.xp[2] / 3, abs=0.02)  # spelar bara 12 september
    assert p.xp[3] == pytest.approx(base.xp[3], abs=0.02)


def make_snapshot_active(snap, pid):
    import copy

    s = copy.deepcopy(snap)
    next(p for p in s.players if p["id"] == pid)["status"] = "active"
    return s


def test_invalid_rows_are_skipped_and_reported(tmp_path):
    rows, errors = exc.parse(
        [
            {"player_id": "1", "reason": "privat", "from": "2026-09-03"},
            {"player_id": "2", "reason": "semester", "from": "2026-09-03"},
            {"player_id": "3", "reason": "vila", "from": "2026-09-05", "to": "2026-09-01"},
            {"reason": "vila", "from": "2026-09-05"},
            {"player_id": "4", "reason": "skada", "from": "inte ett datum"},
        ]
    )
    assert [r.player_id for r in rows] == ["1"]
    assert len(errors) == 4 and all("rad" in e for e in errors)

    (tmp_path / exc.FILE_NAME).write_text("{inte json")
    rows, errors = exc.load(tmp_path)
    assert rows == [] and errors
    assert exc.load(tmp_path / "saknas") == ([], [])


def test_backtest_uses_same_adjustment_as_model():
    snap, pid = _snapshot_with_missed_game()
    # Gör vecka 2 spelad så att backtesten har en vecka att förutsäga
    snap.gameweeks[1]["status"] = "completed"
    for g in snap.games:
        if g["date"].startswith("2026-09-09") or g["date"] in ("2026-09-10", "2026-09-12"):
            g.update(played=True, home_score=2, away_score=1)
    snap.gameweek_points["2"] = {p["id"]: {"games": 1, "points": 4, "pm": 0, "cats": {}} for p in snap.players}
    absences = _absence(pid, "privat", "2026-09-03")

    row = next(r for w in build_weeks(snap, min_week=2, absences=absences) for r in w.rows if r.pid == pid)
    assert row.team_games == 3
    assert recent_play_rate(row.weeks, 1.0) == pytest.approx(1.0)
    no_exc = next(r for w in build_weeks(snap, min_week=2) for r in w.rows if r.pid == pid)
    assert no_exc.team_games == 4


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("STATIC_DIR", raising=False)
    from app import config

    config.get_settings.cache_clear()
    main = importlib.reload(importlib.import_module("app.main"))
    snap, pid = _snapshot_with_missed_game()
    main.store.snapshot = snap
    main.store.version += 1
    yield TestClient(main.app), tmp_path, pid
    config.get_settings.cache_clear()


def test_api_shows_absence_and_picks_up_file_changes(client):
    c, data_dir, pid = client
    before = c.get(f"/api/players/{pid}").json()
    assert before["absence"] is None

    (data_dir / exc.FILE_NAME).write_text(
        json.dumps([{"player_id": pid, "reason": "privat", "from": "2026-09-03", "note": "Blev pappa"}])
    )
    after = c.get(f"/api/players/{pid}").json()
    assert after["absence"]["excused_games"] == 1
    assert after["absence"]["absences"][0]["note"] == "Blev pappa"
    assert after["play_rate"] > before["play_rate"]

    (data_dir / exc.FILE_NAME).write_text(json.dumps([{"player_id": pid, "reason": "okänd", "from": "2026-09-03"}]))
    status = c.get("/api/status").json()
    assert any("Frånvarofilen" in e for e in status["errors"])
