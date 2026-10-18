import { useEffect, useState } from "react";
import { api } from "../api";
import { date, num, signed } from "../format";
import type { MemoryNote, TransferLog } from "../types";

/** AI:ns minne för profilen: anteckningar och byteshistorik med utfall. */
export function MemoryPanel() {
  const [notes, setNotes] = useState<MemoryNote[]>([]);
  const [transfers, setTransfers] = useState<TransferLog[]>([]);
  const [text, setText] = useState("");

  const load = () =>
    api
      .memory()
      .then((m) => {
        setNotes(m.notes);
        setTransfers(m.transfers);
      })
      .catch(() => undefined);

  useEffect(() => {
    void load();
  }, []);

  const settled = transfers.filter((t) => t.net_points !== null);
  const total = settled.reduce((s, t) => s + (t.net_points ?? 0), 0);

  return (
    <section className="card">
      <h2>AI:ns minne</h2>
      <p className="hint">
        AI-rådgivaren läser det här innan den ger råd. Den sparar själv preferenser du nämner i chatten, och du kan
        lägga till egna.
      </p>
      {notes.length === 0 && <p className="hint">Inga anteckningar ännu.</p>}
      <ul className="notes">
        {notes.map((n) => (
          <li key={n.id}>
            <span>{n.text}</span>
            <button
              className="small ghost"
              aria-label="Ta bort anteckning"
              onClick={() => api.deleteNote(n.id).then(load)}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          void api.addNote(text).then(() => {
            setText("");
            void load();
          });
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="T.ex. Jag sparar Fria Byten till jul"
          maxLength={300}
        />
        <button disabled={!text.trim()}>Lägg till</button>
      </form>

      <h3 className="sub">Byteshistorik</h3>
      {transfers.length === 0 ? (
        <p className="hint">Byten du genomför här loggas, och utfallet räknas fram när veckorna spelats.</p>
      ) : (
        <>
          {settled.length > 0 && (
            <p className="hint">
              {settled.length} avgjorda byten, totalt <strong className={total >= 0 ? "good" : "bad"}>{signed(total, 0)} p</strong>{" "}
              jämfört med att ha behållit spelarna.
            </p>
          )}
          <ul className="transfer-log">
            {transfers.map((t) => (
              <li key={t.date}>
                <div>
                  <small>
                    v.{t.gameweek} · {date(t.date)}
                  </small>{" "}
                  <span className="out-name">{t.out.map((p) => p.name).join(", ")}</span> →{" "}
                  <span className="in-name">{t.in.map((p) => p.name).join(", ")}</span>
                </div>
                <div className="hint">
                  Förväntat {signed(t.expected_gain)} xP
                  {t.penalty ? `, −${t.penalty} avdrag` : ""} ·{" "}
                  {t.net_points === null ? (
                    "inga spelade veckor ännu"
                  ) : (
                    <>
                      utfall {t.in_points} − {t.out_points}
                      {t.penalty ? ` − ${t.penalty}` : ""} ={" "}
                      <strong className={t.net_points >= 0 ? "good" : "bad"}>{signed(t.net_points, 0)} p</strong> (
                      {t.weeks_played.length} v.)
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="hint">Snitt per byte: {settled.length ? num(total / settled.length) : "–"} p.</p>
    </section>
  );
}
