"""Spelregler för Fantasy SHL (från fantasy.shl.se/prizes-and-rules)."""

POSITIONS = ("GK", "D", "C", "F")

POSITION_NAMES = {"GK": "Målvakt", "D": "Back", "C": "Center", "F": "Forward"}

# Truppen: 15 spelare
SQUAD_COMPOSITION = {"GK": 2, "D": 5, "C": 3, "F": 5}
SQUAD_SIZE = sum(SQUAD_COMPOSITION.values())

# Laguttagning: två fulla femmor (2 D, 1 C, 2 F vardera) + en målvakt
LINEUP_COMPOSITION = {"GK": 1, "D": 4, "C": 2, "F": 4}
FIRST_FIVE_COMPOSITION = {"GK": 1, "D": 2, "C": 1, "F": 2}

INITIAL_BUDGET = 100.0
MAX_PER_CLUB = 3
TRANSFER_PENALTY = 10
MAX_FREE_TRANSFERS = 2  # 1 per vecka, max 1 sparad

# Bänkspelare ger bara poäng om en startspelare uteblir helt. Vi värderar dem lågt.
BENCH_WEIGHT = 0.1

COACH_CARDS = {
    "fria_byten": "Fria Byten",
    "toppa_laget": "Toppa Laget",
    "anfall": "Anfall",
    "forsvar": "Försvar",
    "juniorer": "Juniorer",
    "veteraner": "Veteraner",
}

JUNIOR_MAX_AGE = 20
VETERAN_MIN_AGE = 33

RULES_TEXT = """\
TRUPP OCH BUDGET
- Truppen består av 15 spelare: 2 målvakter (GK), 5 backar (D), 3 centrar (C), 5 forwards (F).
- Startbudget 100 Mkr. Under säsongen gäller att banken (pengar kvar) aldrig får bli negativ.
- Max 3 spelare från samma SHL-lag.
- Spelarpriser ändras med högst ±0,1 Mkr per match beroende på prestation (efter minst 3 spelade matcher).

LAGUTTAGNING
- Inför varje matchvecka tas två fulla femmor och en målvakt ut: 1 GK, 4 D, 2 C, 4 F.
  Förstafemman = GK + 2 D + 1 C + 2 F, andrafemman = 2 D + 1 C + 2 F. Bänk: 1 GK, 1 D, 1 C, 1 F.
- Bänkspelare ger poäng endast om en startspelare på samma position uteblir från alla veckans matcher.
- Kapten får dubbla poäng. Spelar inte kaptenen tar assisterande kapten över.
- Inga ändringar under pågående matchvecka. Deadline är en timme före veckans första match.

ÖVERGÅNGAR
- 1 gratis övergång per vecka, en osparad sparas (max 2 gratis samtidigt).
- Varje extra övergång kostar 10 poäng.

COACHKORT (ett per vecka, vart och ett en gång per säsong)
- Fria Byten: obegränsat antal byten utan poängavdrag inför en matchvecka.
- Toppa Laget: förstafemman inkl. målvakt får dubbla poäng, andrafemman och bänken får 0. Ingen kaptensbonus.
- Anfall: de fyra spelande forwards (F) får dubbla poäng.
- Försvar: de fyra spelande backarna får dubbla poäng.
- Juniorer: alla spelande spelare upp till och med 20 år får dubbla poäng.
- Veteraner: alla spelande spelare från 33 år får dubbla poäng.
- En spelare kan inte få bonus från både coachkort och kaptensroll samma vecka.

POÄNG UTESPELARE (per match)
- Istid: 1 p (0–9:59), 2 p (10–19:59), 3 p (20:00+)
- Mål 4 p, assist 3 p, matchavgörande mål +2 p, mål i numerärt underläge +3 p
- Två tacklingar 1 p, två blockerade skott 1 p, fyra skott på mål 1 p
- Var tredje tekningsvinst mer än förlust +1 p, var tredje tekningsförlust mer än vinst −1 p
- Plus/minus: +2 p per plus, −2 p per minus
- −1 p per två utvisningsminuter (max −5 per match)

POÄNG MÅLVAKTER (per match)
- Spelat match 1 p, spelat över 40:00 +1 p
- Vinst full tid 3 p, vinst efter förlängning/straffar 2 p, förlust efter förlängning/straffar 1 p
- 1 p per fem räddningar, hållen nolla (vinst) 4 p
- Mål 10 p, assist 3 p, −1 p per insläppt mål, −1 p per två utvisningsminuter
"""
