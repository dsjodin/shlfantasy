# SHL Fantasy-hjälpen

Ett personligt verktyg för Fantasy SHL. Det räknar på byten åt dig (budget, positioner, max 3 per lag och poängavdrag), föreslår optimala byten, kapten och när coachkorten lönar sig, och har en AI-rådgivare som granskar dina val och säger ifrån när det finns bättre alternativ.

## Varifrån kommer datan?

Det behövs ingen skrapning av inloggade sidor. Fantasy SHL publicerar en öppen statistikexport på [fantasy.shl.se/statistics](https://fantasy.shl.se/statistics) med pris, poäng, form, status och ägarandel för alla spelare, plus poäng per matchvecka. Matchschemat och spelarnas födelsedatum (för korten Juniorer och Veteraner) hämtas från shl.se:s öppna API.

Appen hämtar allt automatiskt vid start och sedan en gång i timmen. Födelsedatum hämtas om en gång i veckan. Allt sparas i `data/` så att appen fungerar även om källorna ligger nere en stund.

Istiden per spelare och match hämtas från shl.se:s matchrapporter, en gång per spelad match.

Det enda som inte finns öppet är ditt eget lag. Det lägger du in en gång under "Mitt lag" (15 spelare och vad du har kvar i banken). När du sedan gör ett byte här och trycker på "Genomför i mitt lag" uppdateras laget, banken och antalet gratisbyten automatiskt.

## Flera i familjen

Appen har profiler, ungefär som på Netflix. Varje familjemedlem väljer eller skapar sin profil första gången och får ett eget lag, egen bank, egna coachkort och en egen AI-chatt. Enheten kommer ihåg vilken profil som valdes, och man byter genom att klicka på namnet uppe till höger.

Profilerna har inget lösenord. Det räcker på hemnätet men betyder att vem som helst kan välja någon annans profil. Lagen sparas på servern i `data/teams/<id>.json`, en fil per profil, så det är samma lag oavsett om man öppnar appen i datorn eller telefonen. Fanns det ett lag sedan tidigare (`data/team.json`) flyttas det automatiskt till profilen "Mitt lag".

## Funktioner

- Profiler: ett eget lag per familjemedlem.
- Mitt lag: trupp, bank, gratisbyten och använda coachkort, med regelkontroll och föreslagen laguttagning (två femmor, målvakt, kapten och assisterande kapten).
- Byten: välj vem som ska ut och se direkt vad du har att lägga, vilka som är möjliga och modellens bästa ersättare. Kalkylatorn visar bank efter byte, poängavdrag och förväntad poängförändring vecka för vecka. Optimeraren räknar fram bästa kombinationen av 1 till 4 byten, eller ett helt nytt lag med Fria Byten.
- Långsiktig byteskedja: planerar byten vecka för vecka över 2 till 6 veckor. Gratisbyten sparas (max 2) och varje extra byte kostar 10 poäng, så planen avgör om det lönar sig att ta avdrag nu eller vänta på nästa gratisbyte. Särskilt användbart när gratisbytena är slut. Två veckor efter planen räknas också med, så att sena byten måste hålla även efteråt.
- Kapten och kort: förväntad extra poäng per coachkort och vecka med din trupp, en kortplan som fördelar de kort du har kvar med högst ett kort per vecka, och matchschema per lag och vecka. Förbrukade kort markeras direkt på sidan.
- Coachkort i bytena: bytesförslag, kalkylatorn och den långsiktiga planen räknar med kortplanen. Ett byte som säljer en veteran inför ett Veteraner-kort syns som en sänkning av det kortet, och optimeringen väger in det när den väljer byten (se nedan).
- Spelare: sorterbar och filtrerbar tabell med detaljvy per spelare, inklusive formtrend (pil uppåt eller nedåt), jämnhet (hur stor del av poängen bästa veckan står för) och frånvaroundantag.
- AI-rådgivare: chatt med Claude som har verktyg för att läsa ditt lag, söka spelare, räkna på byten, köra optimeraren och planera byteskedjor. Från bytessidan kan du också låta AI:n granska ett planerat byte.

## Så räknas xP (förväntade poäng)

Modellen är medvetet enkel så att den går att förstå och lita på. Poäng per match krymps mot vad priset förväntar sig för positionen, eftersom Fantasy SHL sätter priset efter förväntad poäng och priset därmed bär mycket information. Det vägs mot andelen av lagets matcher spelaren faktiskt har spelat (viktigt för målvakter) och lite mot formen. Varje match justeras sedan för motståndet (lag som släpper in många mål ger mer för utespelare) och för hemmaplan. Skadade spelare får 0 nästa vecka och trappas sedan upp.

Vikterna är inte gissade utan framtagna med en backtest: för varje redan spelad matchvecka byggs statistiken upp som den såg ut innan veckan, modellen förutsäger veckan och resultatet jämförs med utfallet. Resultatet visas i appen under Spelare, "Hur träffsäker är xP?", och kan köras med `python -m app.backtest --tune`.

Efter matchvecka 2–5 säsongen 2026/27 såg det ut så här: modellen missar i snitt 4,6 poäng per spelare och vecka, och dess bästa elva tog 48 % av poängen som den bästa möjliga elvan i efterhand fick. Säsongssnitt rakt av gav 5,7 respektive 34 %. Motstånd och hemmaplan förbättrade resultatet i tre av fyra veckor. Det säger två saker: modellen är klart bättre än att gå på snittet, och veckopoäng i hockey är så slumpmässiga att ingen modell kommer att träffa enskilda spelare särskilt bra. Värdet ligger i att välja rätt oftare.

Backtesten har en svaghet som bör sägas rakt ut. Fantasy SHL publicerar inte historiska priser, så testet använder dagens pris, som redan har påverkats av de veckor som testas. Det gör att priset ser något klokare ut i efterhand än det var, och därför väger modellen priset lite lägre än vad backtesten själv föreslår.

### Formtrend och PDO

Varje spelare har en formtrend som jämför de senaste veckorna med säsongen, både i poäng per match och i andel av lagets matcher spelaren faktiskt spelat. Båda testades i backtesten mot matchvecka 2–9:

- Speltidstrenden förbättrar prognosen och räknas in i xP. En spelare som petats eller fått en större roll fortsätter oftast så.
- Poängtrenden gör prognosen något sämre. En het poängperiod håller sällan i sig, så den visas som information men räknas inte in. I den långsiktiga planeraren kan man ändå välja att väga in den.
- Plus/minus-poängen räknas som tur. De styrs till stor del av lagets skott- och räddningsprocent när spelaren är på isen (det som kallas PDO), och det jämnar ut sig. Spelare med mycket plus/minus-poäng presterade klart sämre än modellen trodde.

### Kategorimodellen

För utespelare räknas poäng per match kategori för kategori, eftersom kategorierna är olika pålitliga. Mätt som korrelation mellan udda och jämna matchveckor (vecka 1–9):

| Kategori | Andel av poängen | Upprepar sig |
|---|---|---|
| Istid | 56 % | 0,87 |
| Tacklingar, blockerade skott | 9 % | 0,56–0,59 |
| Mål och assist | 36 % | 0,29 |
| Utvisningar, plus/minus, matchavgörande mål | −4 % | 0,04–0,11 |

Istiden, mer än halva poängen, är alltså nästan helt förutsägbar medan mål och assist till stor del är slump. Därför litar modellen nästan helt på spelarens egen istid, krymper mål och assist hårt mot positionens snitt och ersätter tur-kategorierna helt med snittet. Målvakter räknas som tidigare.

Kategorimodellen förbättrade bästa elvan i sju av åtta veckor. Vinsten är störst tidigt i säsongen, när få matcher gör det viktigast att veta vilka poäng som är slump.

### Matchrapporterna från shl.se

Matchrapporterna har istid, kedja, powerplaymål, powerplayskott och skott per spelare, plus vilken målvakt som startade. Allt testades mot backtesten:

- Istidstrend (minuter per match de senaste två veckorna mot säsongen): bättre eller lika i alla åtta testveckor och bättre i varje vecka från vecka 5. Den räknas in i xP och syns i formtrenden. Mer istid betyder större roll, och det syns innan poängen gör det.
- Kedja och powerplay: tillförde ingenting utöver modellen. Priset och kategorimodellen fångar rollen redan.
- Motståndets styrka mätt i skott i stället för mål: bästa elvan svängde kraftigt mellan veckorna och medelfelet blev sämre i fyra veckor. Används inte.
- Målvakter (startandel, krympning): inget försök förbättrade prognosen. Målvakternas veckopoäng är svåra att förutsäga, och underlaget är litet (17 målvakter).

### Heta perioder

Spelare i lag som vunnit alla sina matcher en vecka gör i snitt klart sämre än väntat veckan efter. I testveckorna missade modellen med −1,3 poäng per spelare och vecka för dem, mot +0,3 för övriga. Effekten fanns kvar även i en modell som bara använder pris och speltid, så den kommer inte från formen. En vecka där allt studsar rätt höjer både poängsnittet och priset, men håller sällan i sig. Effekten är borta två veckor senare.

Samma sak gäller en enskild extrem vecka för en spelare, som när Timrå vann med 8–2 och Eddie Genborg tog 45 poäng på en vecka. Den drar upp snittet långt efteråt.

Två korrigeringar finns därför med, båda korsvaliderade (anpassade på udda veckor och prövade på jämna, och tvärtom):

- Avdrag med 0,5 poäng per match nästa vecka för spelare i lag som vann alla sina matcher (minst två) veckan innan.
- En fjärdedel av bästa veckans överskott över spelarens typiska vecka räknas bort. Hårdare dämpning gav sämre resultat.

Tillsammans gav de medelfel 4,15 → 4,10 och bästa elvan 54 % → 57 %. Att väga motståndarens senaste veckor tyngre i lagstyrkan testades också men gav ingen förbättring.

Sammantaget gick medelfelet från 4,38 till 4,10 poäng per spelare och vecka (matchvecka 2–9), korrelationen från 0,45 till 0,50 och bästa elvan från 46 % till 57 %.

### Testat men inte infört: hårdare dämpning av toppveckor

Efter en rådgivningssession testades fler sätt att hantera toppveckor och heta perioder. Alla prövades utanför träningsdatan: för varje testvecka (5–9) valdes variantens inställning på veckorna före, och den mättes sedan på testveckan. Udda/jämna veckor användes som extra kontroll. Kriteriet bestämdes i förväg: medelfelet minst 0,5 % lägre, rangkorrelation och köpträff inte sämre, bättre i en majoritet av testveckorna och åt samma håll i udda/jämna-kontrollen. Köpträff är de faktiska poängen för modellens fem bästa per position som andel av de fem faktiskt bästas.

| Variant | Medelfel | Rangkorr. | Köpträff | Bästa elvan | Veckor bättre | Infört |
|---|---|---|---|---|---|---|
| Dagens modell | 3,919 | 0,500 | 56,1 % | 56,6 % | | |
| a) Tak för mål/assist per vecka (positionens 90:e–97,5:e percentil) | 3,919 | 0,501 | 59,2 % | 56,7 % | 3 av 5 | Nej |
| a) Tak, utan dagens toppveckedämpning | 3,933 | 0,499 | 57,2 % | 55,1 % | 1 av 5 | Nej |
| b) Lagets poäng mot snittet, i stället för vann-allt | 3,938 | 0,485 | 61,2 % | 53,7 % | 2 av 5 | Nej |
| b) Lagets poäng mot snittet, utöver vann-allt | 3,936 | 0,486 | 61,0 % | 57,5 % | 2 av 5 | Nej |
| b) Andel spelare med toppvecka, i stället för vann-allt | 3,914 | 0,502 | 56,9 % | 54,7 % | 2 av 5 | Nej |
| b) Andel spelare med toppvecka, utöver vann-allt | 3,924 | 0,495 | 58,3 % | 58,9 % | 3 av 5 | Nej |
| b) Lagets PDO, i stället för vann-allt | 3,929 | 0,500 | 56,5 % | 53,9 % | 2 av 5 | Nej |
| b) Lagets PDO, utöver vann-allt | 3,922 | 0,493 | 57,2 % | 57,9 % | 2 av 5 | Nej |
| c) Extra krympning av mål/assist över spelarens vanliga nivå | 3,920 | 0,500 | 56,5 % | 56,5 % | 2 av 5 | Nej |
| c) Samma, utan dagens toppveckedämpning | 3,923 | 0,499 | 57,1 % | 55,0 % | 2 av 5 | Nej |
| c) Högre krympning av mål och assist (15–40) | 3,926 | 0,503 | 58,3 % | 58,8 % | 2 av 5 | Nej |
| Starkare toppveckedämpning (0,5 eller 0,75) | 3,918 | 0,497 | 58,4 % | 55,1 % | 2 av 5 | Nej |

Ingen variant förbättrade medelfelet nämnvärt. Flera höjde köpträffen (som mest till 61 %), men utan att medelfelet blev bättre och med bara fem testveckor. Det är värt att köra om när fler veckor spelats. Rangkorrelation, köpträff och den rullande utvärderingen finns kvar i backtesten (`python -m app.backtest`).

### Frånvaro med känd orsak

Statistiken säger bara att en spelare inte spelade, inte varför. Utan mer information sänker frånvaron speltidsandelen och därmed xP, även när spelaren varit borta av privata skäl. Kända orsaker läggs därför för hand i `data/exceptions.json`:

```json
[
  {"player_id": "1674", "reason": "privat", "from": "2026-11-21", "to": "2026-11-21",
   "expected_return": null, "note": "Blev pappa"}
]
```

- `reason`: `privat`, `vila`, `skada` eller `avstängning`. `to` och `expected_return` är valfria.
- Privat och vila: missade lagmatcher inom perioden räknas inte i speltidsandelen.
- Skada och avstängning: andelen räknas som vanligt, eftersom statusen redan hanterar frånvaron. Undantaget syns ändå i spelardatan.
- Kommande matcher inom perioden, eller före `expected_return`, räknas som 0. Med ett återkomstdatum ersätter undantaget statusens allmänna nedtrappning.
- `player_id` är spelarens id i Fantasy SHL. Det finns i `/api/players`, och AI-rådgivaren kan ta fram det om du frågar.

Filen läses om när den ändras, så ingen omstart behövs. Felaktiga rader hoppas över och visas bland felen i statusen. I spelarvyn och för AI-rådgivaren syns undantaget och vad det ändrade, till exempel "speltidsandel 1,00 i stället för 0,83".

### Coachkort i bytesförslagen

Bytesförslagen och den långsiktiga planen räknar med coachkorten. Kort som redan är använda räknas inte, och högst ett kort spelas per vecka.

- Kalkylatorn och planen visar kortplanens värde före och efter, per kort. Det är samma exakta beräkning som på kortsidan, över åtta veckor. "Netto inkl. kort" är bytets nettovinst plus förändringen i kortplanens värde.
- Optimeringen väger in korten när den väljer byten. Laguttagningen med kortet räknas exakt i optimeringen, även när ett kort gör att en svagare men behörig spelare startar, och Toppa Laget betyder ingen kapten den veckan.
- Ett kort som sparas till efter horisonten har ett värde. Det värdet räknas bara på behöriga spelare som redan finns i truppen. En såld veteran sänker alltså värdet av ett sparat Veteraner-kort, men optimeringen köper inte spelare för ett kort långt fram, eftersom det skulle bygga på dagens xP för veckor långt bort.
- Kortschemat och truppen tas fram växelvis. Först räknas den exakta kortplanen för truppen fram, och optimeringen löses med det schemat låst (att spara alla kort prövas också). Sedan räknas kortplanen om för den nya truppen, och optimeringen löses igen om den ändrats. Den bästa lösningen behålls. Att låta optimeringen välja korten helt fritt testades först, men den hann inte lösas: efter 20 sekunder var avståndet till det teoretiskt bästa fortfarande 8 %. Med växlingen tar förslagen cirka 1,5 sekunder och planen några sekunder.
- Optimeringen kan därför föreslå byten som kostar vanliga poäng men höjer kortplanens värde mer, till exempel att köpa en veteran inför en vecka där Veteraner-kortet ger mycket.

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
