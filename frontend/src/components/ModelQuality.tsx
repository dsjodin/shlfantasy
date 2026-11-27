import { useEffect, useState } from "react";
import { api } from "../api";
import { num } from "../format";
import type { ModelQuality as Quality } from "../types";

/** Visar backtesten: hur väl xP hade förutsagt redan spelade matchveckor. */
export function ModelQuality() {
  const [data, setData] = useState<Quality | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (open && !data) api.modelQuality().then(setData).catch(() => undefined);
  }, [open, data]);

  return (
    <details className="card quality" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Hur träffsäker är xP?</summary>
      {!data ? (
        <p className="hint">Räknar…</p>
      ) : data.weeks.length === 0 ? (
        <p className="hint">Inga avslutade matchveckor att testa mot ännu.</p>
      ) : (
        <>
          <p className="hint">
            Modellen har fått förutsäga matchvecka {data.weeks.join(", ")} med bara den statistik som fanns innan
            veckan, och jämförts med utfallet. Medelfel = hur många poäng fel per spelare och vecka. Bästa elvan = hur
            stor andel av den bästa möjliga laguttagningens poäng modellens elva hade fått.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Modell</th>
                  <th>Medelfel</th>
                  <th>Korrelation</th>
                  <th>Bästa elvan</th>
                </tr>
              </thead>
              <tbody>
                {data.archived && (
                  <tr className="mine">
                    <td>
                      {data.archived.name} <small>(v.{data.archived.weeks.join(", ")})</small>
                    </td>
                    <td>{num(data.archived.mae, 2)}</td>
                    <td>{num(data.archived.correlation, 2)}</td>
                    <td>{Math.round(data.archived.lineup_efficiency * 100)} %</td>
                  </tr>
                )}
                {data.models.map((m) => (
                  <tr key={m.key} className={m.key === "current" ? "mine" : ""}>
                    <td>{m.name}</td>
                    <td>{num(m.mae, 2)}</td>
                    <td>{num(m.correlation, 2)}</td>
                    <td>{Math.round(m.lineup_efficiency * 100)} %</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.tuning_log && data.tuning_log.length > 0 && (
            <>
              <h4>Automatisk justering av vikterna</h4>
              <p className="hint">
                Efter varje slutrapporterad matchvecka prövas nya vikter på de två senaste veckorna, som de inte tränats på.
                De tas bara i bruk om de är tydligt bättre.
              </p>
              <ul className="tuning-log">
                {data.tuning_log.map((e) => (
                  <li key={e.date} className={e.adopted ? "good" : ""}>
                    <strong>Efter v.{e.week}:</strong> {e.adopted ? "Nya vikter i bruk. " : ""}
                    {e.reason}
                    {e.current_mae !== undefined && e.candidate_mae !== undefined && (
                      <small>
                        {" "}
                        (medelfel {num(e.current_mae, 2)} → {num(e.candidate_mae, 2)})
                      </small>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="hint">
            Hockeypoäng per vecka är väldigt slumpmässiga – även bästa modellen missar mycket för enskilda spelare. Värdet
            ligger i att välja rätt oftare än man annars hade gjort. Prognoserna sparas vid varje deadline, så raden
            ”Sparade prognoser” är en exakt mätning. Övriga rader räknas fram i efterhand och använder dagens pris för
            veckor innan arkivet fanns, vilket ger pris-baserade modeller en viss fördel.
          </p>
        </>
      )}
    </details>
  );
}
