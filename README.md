# SHL Fantasy-hjälpen

Ett personligt verktyg för Fantasy SHL. Det räknar på byten åt dig (budget, positioner, max 3 per lag och poängavdrag), föreslår optimala byten, kapten och när coachkorten lönar sig, och har en AI-rådgivare som granskar dina val och säger ifrån när det finns bättre alternativ.

## Varifrån kommer datan?

Det behövs ingen skrapning av inloggade sidor. Fantasy SHL publicerar en öppen statistikexport på [fantasy.shl.se/statistics](https://fantasy.shl.se/statistics) med pris, poäng, form, status och ägarandel för alla spelare, plus poäng per matchvecka. Matchschemat och spelarnas födelsedatum (för korten Juniorer och Veteraner) hämtas från shl.se:s öppna API.

Appen hämtar allt automatiskt vid start och sedan en gång i timmen. Födelsedatum hämtas om en gång i veckan. Allt sparas i `data/` så att appen fungerar även om källorna ligger nere en stund.

Det enda som inte finns öppet är ditt eget lag. Det lägger du in en gång under "Mitt lag" (15 spelare och vad du har kvar i banken). När du sedan gör ett byte här och trycker på "Genomför i mitt lag" uppdateras laget, banken och antalet gratisbyten automatiskt.

## Flera i familjen

Appen har profiler, ungefär som på Netflix. Varje familjemedlem väljer eller skapar sin profil första gången och får ett eget lag, egen bank, egna coachkort och en egen AI-chatt. Enheten kommer ihåg vilken profil som valdes, och man byter genom att klicka på namnet uppe till höger.

Profilerna har inget lösenord. Det räcker på hemnätet men betyder att vem som helst kan välja någon annans profil. Lagen sparas på servern i `data/teams/<id>.json`, en fil per profil, så det är samma lag oavsett om man öppnar appen i datorn eller telefonen. Fanns det ett lag sedan tidigare (`data/team.json`) flyttas det automatiskt till profilen "Mitt lag".

## Funktioner

- Profiler: ett eget lag per familjemedlem.
- Mitt lag: trupp, bank, gratisbyten och använda coachkort, med regelkontroll och föreslagen laguttagning (två femmor, målvakt, kapten och assisterande kapten).
- Byten: välj vem som ska ut och se direkt vad du har att lägga, vilka som är möjliga och modellens bästa ersättare. Kalkylatorn visar bank efter byte, poängavdrag och förväntad poängförändring vecka för vecka. Optimeraren räknar fram bästa kombinationen av 1 till 4 byten, eller ett helt nytt lag med Fria Byten.
- Kapten och kort: förväntad extra poäng per coachkort och vecka med din trupp, samt matchschema per lag och vecka.
- Spelare: sorterbar och filtrerbar tabell med detaljvy per spelare.
- AI-rådgivare: chatt med Claude som har verktyg för att läsa ditt lag, söka spelare, räkna på byten och köra optimeraren. Från bytessidan kan du också låta AI:n granska ett planerat byte.

## Så räknas xP (förväntade poäng)

Modellen är medvetet enkel så att den går att förstå och lita på. Poäng per match krymps mot vad priset förväntar sig för positionen när spelaren har få matcher, eftersom Fantasy SHL sätter priset efter förväntad poäng. Det vägs mot andelen av lagets matcher spelaren faktiskt har spelat (viktigt för målvakter) och mot formen de senaste fem lagmatcherna. Därefter multipliceras det med antalet matcher laget spelar den veckan. Skadade spelare får 0 nästa vecka och trappas sedan upp.

Modellen vet ingenting om kedjor, powerplay-roller, målvaktsrotation eller nyheter. Det är därför AI-rådgivaren är instruerad att lyfta sådana osäkerheter i stället för att lita blint på siffrorna.

En sak att känna till: appen räknar med att du säljer en spelare till dagens pris. Om Fantasy SHL använder ett annat försäljningspris för din spelare, justera banken under "Mitt lag".

## Installation på egen server eller NAS

Det som krävs är Docker med Compose.

```bash
git clone https://github.com/dsjodin/shlfantasy.git
cd shlfantasy
cp .env.example .env      # lägg in ANTHROPIC_API_KEY för AI-rådgivaren
docker compose up -d --build
```

Öppna sedan `http://<serverns-ip>:8022`. Första starten tar ungefär en halv minut innan all data är hämtad. Data och ditt lag sparas i `./data`.

Appen har ingen inloggning, så den bör bara exponeras på ditt hemnätverk eller bakom en reverse proxy med autentisering. Annars kan vem som helst använda din API-nyckel.

### AI-rådgivaren

Skapa en API-nyckel på [console.anthropic.com](https://console.anthropic.com) och lägg den i `.env`. Utan nyckel fungerar allt utom AI-delen. Standardmodell är `claude-opus-5-5` med `CLAUDE_EFFORT=medium`. En fråga kostar grovt räknat 1 till 3 kronor beroende på hur många verktygsanrop som behövs (följdfrågor blir billigare tack vare prompt caching). Vill du hålla nere kostnaden kan du sätta `CLAUDE_EFFORT=low` eller `CLAUDE_MODEL=claude-sonnet-5-5`.

Om Claude avböjer en fråga skickas den automatiskt vidare till en reservmodell (server-side fallback), så du får ett svar i stället för ett avslag.

## Utveckling

Backend (Python 3.12+, FastAPI, PuLP med HiGHS som lösare):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python -m app.refresh            # hämta data manuellt
pytest                            # tester
uvicorn app.main:app --reload --port 8022  # API på port 8022
```

Frontend (React, Vite, TypeScript):

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173, proxar /api till port 8022
```

Projektets uppbyggnad:

```
backend/app/
  sources/      hämtning från fantasy.shl.se och shl.se
  datastore.py  cache och schemalagd uppdatering
  model.py      xP-modellen
  squad.py      regler, laguttagning, bytesanalys, coachkort
  optimizer.py  heltalsoptimering av byten
  advisor.py    AI-rådgivaren (Claude + verktyg)
  team_store.py profiler och sparade lag
  main.py       REST-API och servering av frontend
frontend/src/   webbgränssnittet
```
