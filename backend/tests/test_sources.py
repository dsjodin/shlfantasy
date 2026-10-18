from app.sources import fantasy, shl

PLAYERS_CSV = (
    "﻿season,player_shl_id,player_name,club_code,position,status,price_millions,ownership_percent,"
    "games_played,total_fantasy_points,fantasy_points_per_game,form,goals_points,assists_points,"
    "game_winning_goals_points,shorthanded_goals_points,plus_minus_points,time_on_ice_points,"
    "shots_on_goal_points,faceoffs_won_points,blocked_shots_points,penalty_minutes_points,hits_points,"
    "saves_points,goals_against_points,shutouts_points,wins_points,overtime_wins_points,"
    "overtime_losses_points,goalkeeper_appearances_points,other_points\n"
    '2026,4681,"Måns Forsfjäll",SKE,D,active,6,5.25,8,23,2.9,3,0,3,0,0,2,17,0,0,1,-1,1,0,0,0,0,0,0,0,0\n'
    '2026,9999,"Okänd Position",ÖRE,,injured,4.5,0,0,0,0,0,,,,,,,,,,,,,,,,,,,\n'
)


def test_parse_players_handles_bom_unicode_and_blanks():
    players = fantasy.parse_players(PLAYERS_CSV)
    assert len(players) == 2
    first, second = players
    assert first["id"] == "4681"
    assert first["name"] == "Måns Forsfjäll"
    assert first["price"] == 6.0
    assert first["breakdown"]["assists_points"] == 3
    assert first["breakdown"]["penalty_minutes_points"] == -1
    assert second["position"] is None
    assert second["club"] == "ÖRE"
    assert second["breakdown"]["goals_points"] == 0


def test_parse_gameweeks():
    text = (
        "season,gameweek,start_date,end_date,status,csv_url\n"
        "2026,5,2026-10-12,2026-10-18,completed,https://fantasy.shl.se/statistics/gameweeks/5.csv\n"
        "2026,6,2026-10-19,2026-10-25,upcoming,\n"
    )
    gws = fantasy.parse_gameweeks(text)
    assert gws[0]["number"] == 5 and gws[0]["status"] == "completed"
    assert gws[1]["csv_url"] is None


def test_parse_schedule_maps_club_codes():
    data = {
        "gameInfo": [
            {
                "uuid": "g1",
                "startDateTime": "2026-10-20 19:00:00",
                "state": "pre-game",
                "homeTeamInfo": {"code": "OHK", "score": 0},
                "awayTeamInfo": {"code": "SAIK", "score": 0},
            }
        ],
        "teamList": [{"uuid": "t1", "teamCode": "OHK"}],
    }
    games, teams = shl.parse_schedule(data)
    assert games[0]["home"] == "ÖRE"
    assert games[0]["away"] == "SKE"
    assert games[0]["date"] == "2026-10-20"
    assert games[0]["played"] is False
    assert teams == [{"uuid": "t1", "club": "ÖRE"}]
