import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAiConversation } from "../components/AiStream";
import { AiTurns } from "../components/AiTurns";
import { PlayerPicker } from "../components/PlayerPicker";
import { PlayerRow } from "../components/PlayerBits";
import { mkr, num, signed } from "../format";
import { useApp } from "../state";
import { POSITIONS, POSITION_NAMES, type Alternative, type Evaluation, type Suggestion } from "../types";

interface Pair {
  out: string;
  in: string | null;
}

export function TransfersPage() {
  const { team, setTeam, players, horizon, status } = useApp();
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [freeCard, setFreeCard] = useState(false);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [pickerFor, setPickerFor] = useState<number | null>(null);
  const [alts, setAlts] = useState<Record<string, Alternative[]>>({});
  const [error, setError] = useState<string | null>(null);
  const ai = useAiConversation();
  const [followUp, setFollowUp] = useState("");

  const ids = team?.player_ids ?? [];
  const outIds = pairs.map((p) => p.out);
  const inIds = pairs.map((p) => p.in).filter((x): x is string => !!x);
  const complete = pairs.length > 0 && pairs.every((p) => p.in);

  // Utvärdera så fort alla utgående spelare har en ersättare
  useEffect(() => {
    setEvaluation(null);
    if (!complete) return;
    api
      .evaluate({ out: outIds, in: inIds, horizon, free_card: freeCard })
      .then(setEvaluation)
      .catch((e) => setError(String(e)));
  }, [JSON.stringify(pairs), horizon, freeCard, complete]);

  // Hämta bästa ersättare för varje utgående spelare
  useEffect(() => {
    for (const id of outIds) {
      if (alts[`${id}:${horizon}`]) continue;
      api
        .alternatives(id, horizon)
        .then((r) => setAlts((a) => ({ ...a, [`${id}:${horizon}`]: r.options })))
        .catch(() => undefined);
    }
  }, [JSON.stringify(outIds), horizon]);

  const money = useMemo(() => {
    const price = (id: string | null) => (id && players[id] ? players[id].price : 0);
    const sold = pairs.reduce((s, p) => s + price(p.out), 0);
    const bought = pairs.reduce((s, p) => s + price(p.in), 0);
    return { sold, bought, bank: (team?.bank ?? 0) + sold - bought, price };
  }, [pairs, players, team]);

  if (!team) return <p className="empty">Laddar…</p>;
  if (ids.length === 0)
    return <div className="alert info">Lägg in ditt lag under ”Mitt lag” först, så kan du räkna på byten här.</div>;

  const toggleOut = (id: string) => {
    ai.reset();
    setPairs((ps) => (ps.some((p) => p.out === id) ? ps.filter((p) => p.out !== id) : [...ps, { out: id, in: null }]));
  };
  const setIn = (index: number, id: string | null) => {
    ai.reset();
    setPairs((ps) => ps.map((p, i) => (i === index ? { ...p, in: id } : p)));
  };

  const pickerPair = pickerFor !== null ? pairs[pickerFor] : null;
  const clubCountsFor = (index: number) => {
    const counts: Record<string, number> = {};
    const squad = ids.filter((id) => !outIds.includes(id)).concat(pairs.filter((_, i) => i !== index).map((p) => p.in).filter((x): x is string => !!x));
    squad.forEach((id) => players[id] && (counts[players[id].club] = (counts[players[id].club] ?? 0) + 1));
    return counts;
  };

  const apply = async () => {
    if (!confirm("Har du gjort bytet på fantasy.shl.se? Då uppdateras ditt sparade lag här.")) return;
    try {
      const updated = await api.apply({ out: outIds, in: inIds, horizon, free_card: freeCard });
      setTeam(updated);
      setPairs([]);
      ai.reset();
    } catch (e) {
      setError(String(e));
    }
  };

  const loadSuggestion = (s: Suggestion) => {
    ai.reset();
    setPairs(s.out.map((o, i) => ({ out: o, in: s.in[i] ?? null })));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const squad = ids.map((id) => players[id]).filter(Boolean);

  return (
    <div className="page">
      {error && (
        <div className="alert error" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      <div className="two-col">
        <section className="card">
          <h2>Ditt lag – välj vem som ska ut</h2>
          {POSITIONS.map((pos) => (
            <div key={pos} className="pos-group">
              <h3>{POSITION_NAMES[pos]}</h3>
              {squad
                .filter((p) => p.position === pos)
                .map((p) => {
                  const selected = outIds.includes(p.id);
                  return (
                    <PlayerRow
                      key={p.id}
                      player={p}
                      muted={selected}
                      onClick={() => toggleOut(p.id)}
                      actions={
                        <button className={`small ${selected ? "danger" : "ghost"}`} onClick={() => toggleOut(p.id)}>
                          {selected ? "Ångra" : "Sälj"}
                        </button>
                      }
                    />
                  );
                })}
            </div>
          ))}
        </section>

        <div className="stack">
          <section className="card">
            <h2>Byten</h2>
            {pairs.length === 0 && <p className="hint">Klicka på ”Sälj” på en spelare för att börja.</p>}
            {pairs.map((pair, i) => {
              const out = players[pair.out];
              const incoming = pair.in ? players[pair.in] : null;
              const options = (alts[`${pair.out}:${horizon}`] ?? []).slice(0, 3);
              return (
                <div key={pair.out} className="pair">
                  <div className="pair-row">
                    <span className="out">UT</span>
                    <PlayerRow player={out} />
                  </div>
                  <div className="pair-row">
                    <span className="in">IN</span>
                    {incoming ? (
                      <PlayerRow
                        player={incoming}
                        actions={
                          <button className="small ghost" onClick={() => setPickerFor(i)}>
                            Ändra
                          </button>
                        }
                      />
                    ) : (
                      <button className="slot" onClick={() => setPickerFor(i)}>
                        + Välj ersättare
                      </button>
                    )}
                  </div>
                  {options.length > 0 && (
                    <div className="alts">
                      <span className="hint">Modellens bästa:</span>
                      {options.map((o) => {
                        const p = players[o.player_id];
                        if (!p) return null;
                        return (
                          <button
                            key={o.player_id}
                            className={`alt ${pair.in === o.player_id ? "active" : ""}`}
                            onClick={() => setIn(i, o.player_id)}
                            title={`Bank efter: ${mkr(o.bank_after)}`}
                          >
                            {p.name} <small>{p.club} · {mkr(p.price)} · {signed(o.xp_gain)} xP</small>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {pairs.length > 0 && (
              <>
                <div className="summary mini">
                  <div className="stat">
                    <span>Bank efter</span>
                    <strong className={money.bank < 0 ? "bad" : ""}>{mkr(money.bank)}</strong>
                  </div>
                  <div className="stat">
                    <span>Byten / gratis</span>
                    <strong>
                      {pairs.length} / {team.free_transfers}
                    </strong>
                  </div>
                  <div className="stat">
                    <span>Poängavdrag</span>
                    <strong className={evaluation?.penalty ? "bad" : ""}>
                      {evaluation ? (evaluation.penalty ? `−${evaluation.penalty}` : "0") : "–"}
                    </strong>
                  </div>
                </div>
                <label className="check">
                  <input type="checkbox" checked={freeCard} onChange={(e) => setFreeCard(e.target.checked)} />
                  Använd coachkortet Fria Byten {team.used_cards.includes("fria_byten") && <em>(redan använt)</em>}
                </label>
              </>
            )}

            {evaluation && <EvaluationView evaluation={evaluation} />}

            {complete && (
              <div className="toolbar">
                {status?.ai_enabled && (
                  <button
                    className="primary"
                    disabled={ai.busy}
                    onClick={() => {
                      ai.reset();
                      void ai.run("/api/ai/review", { out: outIds, in: inIds, horizon }, null);
                    }}
                  >
                    🤖 Låt AI granska bytet
                  </button>
                )}
                <button disabled={!evaluation?.valid} onClick={apply}>
                  Genomför i mitt lag
                </button>
                <button className="ghost" onClick={() => (setPairs([]), ai.reset())}>
                  Rensa
                </button>
              </div>
            )}
          </section>

          {ai.turns.length > 0 && (
            <section className="card ai-card">
              <h2>AI-granskning</h2>
              <AiTurns turns={ai.turns} />
              <form
                className="chat-input"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!followUp.trim()) return;
                  void ai.run("/api/ai/chat", { message: followUp }, followUp);
                  setFollowUp("");
                }}
              >
                <input
                  value={followUp}
                  onChange={(e) => setFollowUp(e.target.value)}
                  placeholder="Ställ en följdfråga…"
                  disabled={ai.busy}
                />
                <button disabled={ai.busy || !followUp.trim()}>Skicka</button>
              </form>
            </section>
          )}

          <SuggestPanel onLoad={loadSuggestion} />
        </div>
      </div>

      {pickerPair && pickerFor !== null && (
        <PlayerPicker
          position={players[pickerPair.out].position}
          title={`Ersättare för ${players[pickerPair.out].name}`}
          excludeIds={[...ids, ...inIds.filter((id) => id !== pickerPair.in)]}
          maxPrice={money.bank + money.price(pickerPair.in)}
          clubCounts={clubCountsFor(pickerFor)}
          onPick={(p) => {
            setIn(pickerFor, p.id);
            setPickerFor(null);
          }}
          onClose={() => setPickerFor(null)}
        />
      )}
    </div>
  );
}

function EvaluationView({ evaluation: e }: { evaluation: Evaluation }) {
  const max = Math.max(...e.per_week.flatMap((w) => [w.before, w.after]), 1);
  return (
    <div className="evaluation">
      {e.issues.length > 0 && (
        <ul className="issues">
          {e.issues.map((i, k) => (
            <li key={k} className={i.level}>
              {i.message}
            </li>
          ))}
        </ul>
      )}
      <div className={`verdict ${e.net_gain > 0 ? "good" : "bad"}`}>
        <strong>{signed(e.net_gain)} xP</strong> netto över {e.gameweeks.length} veckor
        <small>
          ({signed(e.xp_gain_horizon)} xP{e.penalty ? `, −${e.penalty} i avdrag` : ""}) · nästa vecka{" "}
          {num(e.xp_next_before)} → {num(e.xp_next_after)}
        </small>
      </div>
      <div className="bars">
        {e.per_week.map((w) => (
          <div key={w.gameweek} className="bar-group">
            <div className="bar-pair">
              <div className="bar before" style={{ height: `${(w.before / max) * 100}%` }} title={`Före: ${num(w.before)}`} />
              <div className="bar after" style={{ height: `${(w.after / max) * 100}%` }} title={`Efter: ${num(w.after)}`} />
            </div>
            <span>v.{w.gameweek}</span>
          </div>
        ))}
        <div className="legend">
          <span className="sw before" /> Före <span className="sw after" /> Efter
        </div>
      </div>
    </div>
  );
}

function SuggestPanel({ onLoad }: { onLoad: (s: Suggestion) => void }) {
  const { players, horizon, team } = useApp();
  const [maxTransfers, setMaxTransfers] = useState(2);
  const [freeCard, setFreeCard] = useState(false);
  const [options, setOptions] = useState<Suggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.suggest({ horizon, max_transfers: maxTransfers, free_card: freeCard, keep: [], avoid: [] });
      setOptions(r.options);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>Föreslå byten</h2>
      <p className="hint">
        Optimeraren testar alla kombinationer mot budget, max 3 per lag och poängavdrag, för de kommande {horizon}{" "}
        veckorna.
      </p>
      <div className="toolbar">
        <label>
          Max byten{" "}
          <select value={maxTransfers} onChange={(e) => setMaxTransfers(Number(e.target.value))} disabled={freeCard}>
            {[1, 2, 3, 4].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={freeCard} onChange={(e) => setFreeCard(e.target.checked)} /> Fria Byten
        </label>
        <button className="primary" onClick={run} disabled={busy}>
          {busy ? "Räknar…" : "Räkna fram förslag"}
        </button>
      </div>
      {error && <div className="alert error">{error}</div>}
      {options && options.length === 0 && (
        <p className="hint">Inga byten förbättrar laget tillräckligt – spara bytet till nästa vecka.</p>
      )}
      {options?.map((o, k) => (
        <div key={k} className="suggestion">
          <div className="suggestion-head">
            <strong className={o.net_gain > 0 ? "good" : "bad"}>{signed(o.net_gain)} xP netto</strong>
            <span className="hint">
              {o.out.length} byte{o.out.length > 1 ? "n" : ""}
              {o.penalty ? ` · −${o.penalty} avdrag` : ""} · bank {mkr(o.bank_after)}
            </span>
            <button className="small" onClick={() => onLoad(o)}>
              Ladda i kalkylatorn
            </button>
          </div>
          {o.out.map((id, i) => (
            <div key={id} className="swap">
              <span className="out-name">{players[id]?.name}</span>
              <span className="arrow">→</span>
              <span className="in-name">
                {players[o.in[i]]?.name} <small>{players[o.in[i]]?.club} · {mkr(players[o.in[i]]?.price ?? 0)}</small>
              </span>
            </div>
          ))}
        </div>
      ))}
      {team && team.free_transfers === 0 && !freeCard && (
        <p className="hint">Du har inga gratis byten – varje byte kostar 10 poäng.</p>
      )}
    </section>
  );
}
