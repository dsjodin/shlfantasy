import json

import pytest

from app.squad import TeamState
from app.team_store import ProfileNotFound, TeamStore


def test_profiles_are_separate(tmp_path):
    store = TeamStore(tmp_path)
    anna = store.create("Anna")
    olle = store.create("  Olle  ")
    assert olle["name"] == "Olle"
    store.save(anna["id"], TeamState(player_ids=["1", "2"], bank=3.5, free_transfers=2))
    assert store.load(anna["id"]).bank == 3.5
    assert store.load(olle["id"]).player_ids == []
    assert [p["name"] for p in store.profiles()] == ["Anna", "Olle"]


def test_rename_and_delete(tmp_path):
    store = TeamStore(tmp_path)
    p = store.create("Pappa")
    store.rename(p["id"], "Daniel")
    assert store.profiles() == [{"id": p["id"], "name": "Daniel"}]
    store.delete(p["id"])
    assert store.profiles() == []
    with pytest.raises(ProfileNotFound):
        store.load(p["id"])


def test_rejects_path_traversal(tmp_path):
    store = TeamStore(tmp_path)
    assert not store.exists("../snapshot")
    with pytest.raises(ProfileNotFound):
        store.load("../../etc/passwd")


def test_empty_name_rejected(tmp_path):
    with pytest.raises(ValueError):
        TeamStore(tmp_path).create("   ")


def test_legacy_team_is_migrated(tmp_path):
    (tmp_path / "team.json").write_text(json.dumps({"player_ids": ["7"], "bank": 1.2, "free_transfers": 1}))
    store = TeamStore(tmp_path)
    [profile] = store.profiles()
    assert profile["name"] == "Mitt lag"
    assert store.load(profile["id"]).player_ids == ["7"]
    assert not (tmp_path / "team.json").exists()
    # Andra starten ska inte skapa en ny profil
    assert len(TeamStore(tmp_path).profiles()) == 1
