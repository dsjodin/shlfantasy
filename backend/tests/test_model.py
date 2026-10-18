from app.model import build_model
from app.projection import Params

NEUTRAL = Params(opponent_weight=0.0, home_advantage=0.0)


def test_next_gameweek_and_horizon(model):
    assert model.next_gameweek == 2
    assert model.horizon(5) == [2, 3]


def test_games_per_gameweek(model):
    assert model.games_in("AAA", 2) == 3
    assert model.games_in("FFF", 2) == 0
    assert model.games_in("FFF", 3) == 1


def test_xp_scales_with_games(snapshot):
    model = build_model(snapshot, NEUTRAL)
    aaa = next(p for p in model.players.values() if p.club == "AAA" and p.position == "F")
    fff = next(p for p in model.players.values() if p.club == "FFF" and p.position == "F")
    assert aaa.xp[2] == round(aaa.xp_per_game * 3, 2)
    assert fff.xp[2] == 0.0
    assert fff.xp[3] > 0


def test_injured_player_gets_zero_next_week(snapshot):
    snapshot.players[0]["status"] = "injured"
    model = build_model(snapshot)
    p = model.players[snapshot.players[0]["id"]]
    assert p.xp[2] == 0.0
    assert p.xp[3] > 0


def test_play_rate_penalises_backup(snapshot):
    snapshot.players[0]["games_played"] = 1  # lagets matcher: 4
    model = build_model(snapshot)
    backup = model.players[snapshot.players[0]["id"]]
    starter = model.players[snapshot.players[1]["id"]]
    assert backup.play_rate < 0.5
    assert starter.play_rate == 1.0


def test_age_and_find(snapshot):
    snapshot.athletes = {"u1": {"player_id": snapshot.players[0]["id"], "birth_date": "2006-09-10"}}
    model = build_model(snapshot)
    p = model.players[snapshot.players[0]["id"]]
    from datetime import date

    assert p.age_on(date(2026, 9, 9)) == 19
    assert p.age_on(date(2026, 9, 10)) == 20
    assert model.find(p.name.lower()) == [p]
    assert len(model.find("AAA")) == 12
