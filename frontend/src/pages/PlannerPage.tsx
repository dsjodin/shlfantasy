import { useEffect, useState } from "react";
import { api } from "../api";
import { date, signed } from "../format";
import { useApp } from "../state";
import type { CardPlanItem, CardWeek, Fixture } from "../types";
import { LineupCard } from "./TeamPage";

const CARD_HELP: Record<string, string> = {
  toppa_laget: "Förstafemman + MV dubbla, andrafemman 0, ingen kapten",
  anfall: "4 spelande forwards dubbla",
  forsvar: "4 spelande backar dubbla",
  juniorer: "Spelare ≤ 20 år dubbla",
  veteraner: "Spelare ≥ 33 år dubbla",
};

export function PlannerPage() {
  const { team, setTeam, players, status } = useApp();
  const [weeks, setWeeks] = useState<CardWeek[]>([]);
  const [cardPlan, setCardPlan] = useState<CardPlanItem[]>([]);
  const used = team?.used_cards ?? [];
  const [fixtures, setFixtures] = useState<Awaited<ReturnType<typeof api.fixtures>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.fixtures(8).then(setFixtures).catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (!team?.player_ids.length) return;
    api
      .cards(8)
      .then((r) => {
        setWeeks(r.weeks);
        setCardPlan(r.plan);
      })
      .catch((e) => setError(String(e)));
  }, [team]);

  const toggleUsed = async (key: string) => {
    const next = used.includes(key) ? used.filter((c) => c !== key) : [...used, key];
    try {
      setTeam(await api.setUsedCards(next));
    } catch (e) {
      setError(String(e));
    }
  };

  const cardKeys = weeks[0] ? Object.keys(weeks[0].cards) : [];
  const best: Record<string, number> = {};
  for (const key of cardKeys) {
    best[key] = Math.max(...weeks.map((w) => w.cards[key].gain ?? -Infinity));
  }
  const planned = new Map(cardPlan.map((c) => [`${c.gameweek}:${c.card}`, c]));

  return (
    <div className="page">
      {error && <div className="alert error">{error}</div>}
      <div className="two-col">
        <div className="stack">
          {team?.lineup ? <LineupCard lineup={team.lineup} /> : <div className="alert info">Lägg in ditt lag för att få kaptensförslag.</div>}
        </div>
        <div className="stack">
          {weeks.length > 0 && (
            <section className="card">
              <h2>Coachkort – förväntad extra poäng</h2>
              <div className="cards-used">
                <span className="hint">Förbrukade kort:</span>
                {Object.entries(status?.rules.cards ?? {}).map(([key, name]) => (
                  <label key={key} className="check">
                    <input type="checkbox" checked={used.includes(key)} onChange={() => void toggleUsed(key)} /> {name}
                  </label>
                ))}
              </div>
              <h3>Kortplan</h3>
              {cardPlan.length === 0 ? (
                <p className="hint">Inget kvarvarande kort ger minst 1 extra poäng de kommande veckorna. Spara korten.</p>
              ) : (
                <ul className="card-plan">
                  {cardPlan.map((c) => (
                    <li key={c.card}>
                      <strong>v.{c.gameweek}</strong> {c.name} <span className="good">{signed(c.gain)} xP</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="hint">
                Bara ett coachkort får spelas per vecka, så planen fördelar korten du har kvar så att den sammanlagda
                vinsten blir störst. Det kan betyda att ett kort hamnar på sin näst bästa vecka. Kort som inte finns med
                sparas till senare i säsongen. Tabellen nedan visar varje kort för sig, jämfört med en vanlig vecka med
                kapten. Räknat på din nuvarande trupp – planerade byten ändrar bilden.
              </p>
              <div className="table-wrap">
                <table className="cards-table">
                  <thead>
                    <tr>
                      <th>Vecka</th>
                      {cardKeys.map((k) => (
                        <th key={k} title={CARD_HELP[k]}>
                          {weeks[0].cards[k].name}
                          {weeks[0].cards[k].used && <small> (använt)</small>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {weeks.map((w) => (
                      <tr key={w.gameweek}>
                        <td>
                          v.{w.gameweek} <small>{date(w.start)}</small>
                          <br />
                          <small>{w.squad_games} matcher i startelvan</small>
                        </td>
                        {cardKeys.map((k) => {
                          const c = w.cards[k];
                          const inPlan = planned.has(`${w.gameweek}:${k}`);
                          return (
                            <td
                              key={k}
                              className={`${c.used ? "used" : ""} ${!c.used && c.gain !== null && c.gain === best[k] ? "best" : ""} ${inPlan ? "planned" : ""}`}
                              title={inPlan ? "Med i kortplanen" : undefined}
                            >
                              {c.gain === null ? "–" : signed(c.gain)}
                              {inPlan && " ★"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {weeks[0] && (
                <p className="hint">
                  Juniorer i laget: {weeks[0].juniors.map((id) => players[id]?.name).join(", ") || "inga"}. Veteraner:{" "}
                  {weeks[0].veterans.map((id) => players[id]?.name).join(", ") || "inga"}. ★ = med i kortplanen. Fria
                  Byten räknas fram under Byten → Föreslå byten, och den veckan kan inget annat kort spelas.
                </p>
              )}
            </section>
          )}
        </div>
      </div>

      {fixtures && <FixtureGrid data={fixtures} myClubs={new Set((team?.player_ids ?? []).map((id) => players[id]?.club))} />}
    </div>
  );
}

function FixtureGrid({
  data,
  myClubs,
}: {
  data: { gameweeks: { number: number; start: string; end: string }[]; clubs: Record<string, Record<string, Fixture[]>> };
  myClubs: Set<string | undefined>;
}) {
  return (
    <section className="card">
      <h2>Matchschema per vecka</h2>
      <p className="hint">Fler matcher = fler chanser till poäng. Fet stil = lag du har spelare i. H = hemma, B = borta.</p>
      <div className="table-wrap">
        <table className="fixtures">
          <thead>
            <tr>
              <th>Lag</th>
              {data.gameweeks.map((gw) => (
                <th key={gw.number}>
                  v.{gw.number}
                  <br />
                  <small>
                    {date(gw.start)}–{date(gw.end)}
                  </small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.clubs).map(([club, weeks]) => (
              <tr key={club} className={myClubs.has(club) ? "mine" : ""}>
                <td className="name">{club}</td>
                {data.gameweeks.map((gw) => {
                  const games = weeks[gw.number] ?? [];
                  return (
                    <td key={gw.number} className={`games-${Math.min(games.length, 4)}`}>
                      <strong>{games.length}</strong>
                      <small>{games.map((g) => `${g.home ? "H" : "B"} ${g.opponent}`).join(" · ")}</small>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
