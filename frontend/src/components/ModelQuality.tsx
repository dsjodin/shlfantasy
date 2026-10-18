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
          <p className="hint">
            Hockeypoäng per vecka är väldigt slumpmässiga – även bästa modellen missar mycket för enskilda spelare. Värdet
            ligger i att välja rätt oftare än man annars hade gjort. Obs: historiska priser finns inte, så backtesten
            använder dagens pris, vilket ger pris-baserade modeller en viss fördel i efterhand.
          </p>
        </>
      )}
    </details>
  );
}
