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

Modellen är medvetet enkel så att den går att förstå och lita på. Poäng per match krymps mot vad priset förväntar sig för positionen, eftersom Fantasy SHL sätter priset efter förväntad poäng och priset därmed bär mycket information. Det vägs mot andelen av lagets matcher spelaren faktiskt har spelat (viktigt för målvakter) och lite mot formen. Varje match justeras sedan för motståndet (lag som släpper in många mål ger mer för utespelare) och för hemmaplan. Skadade spelare får 0 nästa vecka och trappas sedan upp.

Vikterna är inte gissade utan framtagna med en backtest: för varje redan spelad matchvecka byggs statistiken upp som den såg ut innan veckan, modellen förutsäger veckan och resultatet jämförs med utfallet. Resultatet visas i appen under Spelare, "Hur träffsäker är xP?", och kan köras med `python -m app.backtest --tune`.

Efter matchvecka 2–5 säsongen 2026/27 såg det ut så här: modellen missar i snitt 4,6 poäng per spelare och vecka, och dess bästa elva tog 48 % av poängen som den bästa möjliga elvan i efterhand fick. Säsongssnitt rakt av gav 5,7 respektive 34 %. Motstånd och hemmaplan förbättrade resultatet i tre av fyra veckor. Det säger två saker: modellen är klart bättre än att gå på snittet, och veckopoäng i hockey är så slumpmässiga att ingen modell kommer att träffa enskilda spelare särskilt bra. Värdet ligger i att välja rätt oftare.

Backtesten har en svaghet som bör sägas rakt ut. Fantasy SHL publicerar inte historiska priser, så testet använder dagens pris, som redan har påverkats av de veckor som testas. Det gör att priset ser något klokare ut i efterhand än det var, och därför väger modellen priset lite lägre än vad backtesten själv föreslår.

## Lär sig systemet?

Ja, på tre sätt.

Prognosarkivet sparar inför varje matchvecka modellens prognos och priserna vid deadline (`data/history/gw<N>.json`). Filen skrivs om varje timme tills veckan startar och fryses sedan. Det ger en exakt mätning i efterhand av vad modellen faktiskt trodde, och löser prisproblemet ovan för alla veckor från och med nu.

Vikterna justeras automatiskt efter varje slutrapporterad matchvecka (`data/params.json`). Nya vikter tas fram på alla veckor utom de två senaste och prövas sedan på just de två, som de aldrig sett. De tas bara i bruk om medelfelet blir minst 1 % lägre och den bästa elvan inte blir sämre. Med få veckor är risken stor att anpassa sig efter slumpen, därför spärrarna. Varje prövning loggas och syns i appen. Första prövningen efter vecka 5 gav en kandidat som bara var 0,0 % bättre, så vikterna behölls.

AI-rådgivaren har ett minne per profil. Varje byte som genomförs i appen loggas med förväntad vinst, och när veckorna spelats räknas det faktiska utfallet fram (poäng för köpta minus sålda spelare, minus avdrag). AI:n sparar också preferenser och planer som du nämner i chatten. Den läser minnet innan den ger råd och kan peka på mönster, till exempel att du ofta köper spelare på formtopp som sedan dalar. Minnet syns och kan redigeras under Mitt lag.

Modellen vet fortfarande ingenting om kedjor, powerplay-roller eller nyheter. Där kommer AI-rådgivaren in: den kan söka på webben efter skador, laguppställningar och målvaktsbesked innan den rekommenderar något, och visar källorna.

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

AI:n har webbsökning påslagen som standard (högst 5 sökningar per fråga). Varje sökning kostar ungefär 10 öre utöver tokens. Stäng av med `AI_WEB_SEARCH=false`.

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
  projection.py poängformeln (pris, speltid, form, motstånd, hemmaplan)
  backtest.py   mäter modellen mot spelade matchveckor
  archive.py    sparar prognos och priser vid varje deadline
  tuning.py     automatisk justering av vikterna med spärrar
  memory.py     AI:ns minne per profil (anteckningar, byteshistorik)
  squad.py      regler, laguttagning, bytesanalys, coachkort
  optimizer.py  heltalsoptimering av byten
  advisor.py    AI-rådgivaren (Claude + verktyg)
  team_store.py profiler och sparade lag
  main.py       REST-API och servering av frontend
frontend/src/   webbgränssnittet
```
