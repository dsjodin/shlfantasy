"""API-test med syntetisk data: profiler och att lagen hålls isär."""

import importlib

import pytest
from fastapi.testclient import TestClient

from .conftest import cheapest_valid_squad, make_snapshot


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("STATIC_DIR", raising=False)
    from app import config

    config.get_settings.cache_clear()
    main = importlib.reload(importlib.import_module("app.main"))
    main.store.snapshot = make_snapshot()
    main.store.version += 1
    # Ingen nätverkshämtning i test: kör appen utan lifespan
    yield TestClient(main.app), main
    config.get_settings.cache_clear()


def test_team_requires_profile(client):
    c, _ = client
    assert c.get("/api/team").status_code == 400
    assert c.get("/api/team", headers={"X-Profile": "deadbeef"}).status_code == 400


def test_profiles_keep_teams_apart(client):
    c, main = client
    anna = c.post("/api/profiles", json={"name": "Anna"}).json()
    olle = c.post("/api/profiles", json={"name": "Olle"}).json()
    ids = cheapest_valid_squad(main.current_model())

    r = c.put("/api/team", json={"player_ids": ids, "bank": 5, "free_transfers": 1}, headers={"X-Profile": anna["id"]})
    assert r.status_code == 200 and r.json()["valid"]

    assert c.get("/api/team", headers={"X-Profile": anna["id"]}).json()["player_ids"] == ids
    assert c.get("/api/team", headers={"X-Profile": olle["id"]}).json()["player_ids"] == []

    names = [p["name"] for p in c.get("/api/profiles").json()["profiles"]]
    assert names == ["Anna", "Olle"]

    c.patch(f"/api/profiles/{olle['id']}", json={"name": "Olof"})
    left = c.delete(f"/api/profiles/{anna['id']}").json()["profiles"]
    assert left == [{"id": olle["id"], "name": "Olof"}]


def test_apply_transfer_updates_only_own_profile(client):
    c, main = client
    p = c.post("/api/profiles", json={"name": "Anna"}).json()
    h = {"X-Profile": p["id"]}
    model = main.current_model()
    ids = cheapest_valid_squad(model)
    c.put("/api/team", json={"player_ids": ids, "bank": 5, "free_transfers": 1}, headers=h)
    out = ids[-1]
    clubs = [model.players[i].club for i in ids if i != out]
    new = next(
        x.id
        for x in model.players.values()
        if x.position == model.players[out].position
        and x.id not in ids
        and x.price <= model.players[out].price + 5
        and clubs.count(x.club) < 3
    )
    r = c.post("/api/transfers/apply", json={"out": [out], "in": [new], "horizon": 2}, headers=h)
    assert r.status_code == 200, r.text
    team = r.json()
    assert new in team["player_ids"] and out not in team["player_ids"]
    assert team["free_transfers"] == 0


def test_memory_endpoints_and_transfer_log(client):
    c, main = client
    p = c.post("/api/profiles", json={"name": "Anna"}).json()
    h = {"X-Profile": p["id"]}
    note = c.post("/api/memory/notes", json={"text": "Gillar backar från FHC"}, headers=h).json()
    assert c.get("/api/memory", headers=h).json()["notes"] == [note]
    assert c.delete(f"/api/memory/notes/{note['id']}", headers=h).status_code == 200
    assert c.delete(f"/api/memory/notes/{note['id']}", headers=h).status_code == 404

    model = main.current_model()
    ids = cheapest_valid_squad(model)
    c.put("/api/team", json={"player_ids": ids, "bank": 5, "free_transfers": 1}, headers=h)
    out = ids[-1]
    clubs = [model.players[i].club for i in ids if i != out]
    new = next(
        x.id for x in model.players.values()
        if x.position == model.players[out].position and x.id not in ids and clubs.count(x.club) < 3
        and x.price <= model.players[out].price + 5
    )
    c.post("/api/transfers/apply", json={"out": [out], "in": [new], "horizon": 2}, headers=h)
    [logged] = c.get("/api/memory", headers=h).json()["transfers"]
    assert logged["in"][0]["id"] == new and logged["net_points"] is None
