import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAiConversation } from "../components/AiStream";
import { AiTurns } from "../components/AiTurns";
import { PlayerPicker } from "../components/PlayerPicker";
import { PlayerRow, TrendArrow } from "../components/PlayerBits";
import { mkr, num, signed } from "../format";
import { useApp } from "../state";
import {
  POSITIONS,
  POSITION_NAMES,
  type Alternative,
  type CardImpact,
  type CardScheduleItem,
  type Evaluation,
  type Suggestion,
  type TransferPlan,
} from "../types";

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

          <PlanPanel onLoad={(out, inn) => loadSuggestion({ out, in: inn } as Suggestion)} />
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
      <div className={`verdict ${e.net_gain_incl_cards > 0 ? "good" : "bad"}`}>
        <strong>{signed(e.net_gain)} xP</strong> netto över {e.gameweeks.length} veckor
        <small>
          ({signed(e.xp_gain_horizon)} xP{e.penalty ? `, −${e.penalty} i avdrag` : ""}) · nästa vecka{" "}
          {num(e.xp_next_before)} → {num(e.xp_next_after)}
        </small>
      </div>
      <CardImpactView cards={e.cards} netInclCards={e.net_gain_incl_cards} />
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
            <strong className={o.net_gain_incl_cards > 0 ? "good" : "bad"}>
              {signed(o.net_gain_incl_cards)} xP netto
            </strong>
            <span className="hint">
              {o.out.length} byte{o.out.length > 1 ? "n" : ""}
              {o.penalty ? ` · −${o.penalty} avdrag` : ""} · bank {mkr(o.bank_after)}
              {o.cards && o.cards.change !== 0 ? ` · varav kort ${signed(o.cards.change)}` : ""}
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

function PlanPanel({ onLoad }: { onLoad: (out: string[], inn: string[]) => void }) {
  const { players, team } = useApp();
  const noFree = (team?.free_transfers ?? 0) === 0;
  const [weeks, setWeeks] = useState(4);
  const [maxPerWeek, setMaxPerWeek] = useState(2);
  const [allowHits, setAllowHits] = useState(true);
  const [pointsTrend, setPointsTrend] = useState(false);
  const [plan, setPlan] = useState<TransferPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setPlan(await api.plan({ weeks, max_per_week: maxPerWeek, allow_hits: allowHits, points_trend: pointsTrend }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const first = plan?.weeks[0];
  const tail = plan ? plan.weeks.filter((w) => !w.transfer_week) : [];

  return (
    <section className={`card ${noFree ? "highlight" : ""}`}>
      <h2>Långsiktig byteskedja</h2>
      <p className="hint">
        Planerar byten vecka för vecka. Gratisbyten sparas (max 2) och varje extra byte kostar 10 poäng, så planen
        avgör själv om det lönar sig att ta ett avdrag nu eller vänta på nästa gratisbyte. Två veckor efter planen
        räknas också med, så att sena byten måste hålla även efteråt.
        {noFree && <strong> Du har inga gratisbyten kvar, det är precis här planen gör mest nytta.</strong>}
      </p>
      <div className="toolbar">
        <label>
          Veckor{" "}
          <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            {[2, 3, 4, 5, 6].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label>
          Max byten/vecka{" "}
          <select value={maxPerWeek} onChange={(e) => setMaxPerWeek(Number(e.target.value))}>
            {[1, 2, 3].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label className="check" title="Tillåt byten utöver gratisbytena (−10 poäng styck)">
          <input type="checkbox" checked={allowHits} onChange={(e) => setAllowHits(e.target.checked)} /> Tillåt −10
        </label>
        <label
          className="check"
          title="Lägger till en del av skillnaden mellan senaste veckornas poäng per match och säsongssnittet. Backtesten visar att det inte förbättrar prognosen, så det är avstängt som standard."
        >
          <input type="checkbox" checked={pointsTrend} onChange={(e) => setPointsTrend(e.target.checked)} /> Väg in
          poängformen
        </label>
        <button className="primary" onClick={run} disabled={busy}>
          {busy ? "Planerar…" : "Planera"}
        </button>
      </div>
      {pointsTrend && (
        <p className="hint">
          Poängformen vägs in. Speltidstrenden finns alltid med i xP. Poängformen gör prognosen marginellt sämre i
          backtesten (se Spelare → ”Hur träffsäker är xP?”), så se det som ett sätt att testa en magkänsla.
        </p>
      )}
      {error && <div className="alert error">{error}</div>}
      {plan && (
        <>
          <div className={`verdict ${plan.net_gain_incl_cards > 0 ? "good" : plan.transfers === 0 ? "" : "bad"}`}>
            {plan.transfers === 0 ? (
              <strong>Behåll laget – inga byten lönar sig under perioden</strong>
            ) : (
              <strong>{signed(plan.net_gain_incl_cards)} xP netto inkl. kort</strong>
            )}
            <small>
              {plan.transfers} byten · {plan.penalty ? `−${plan.penalty} i avdrag` : "inga avdrag"} · v.
              {plan.gameweeks[0]}–{plan.gameweeks[plan.gameweeks.length - 1]} · {num(plan.xp_hold)} →{" "}
              {num(plan.xp_plan)} xP
            </small>
          </div>
          <CardScheduleView schedule={plan.card_schedule} />
          <CardImpactView cards={plan.cards} netInclCards={plan.net_gain_incl_cards} />
          <div className="plan">
            {plan.weeks
              .filter((w) => w.transfer_week)
              .map((w) => (
                <div key={w.gameweek} className="plan-week">
                  <div className="plan-week-head">
                    <strong>v.{w.gameweek}</strong>
                    <span className="hint">
                      {w.free_before} gratis
                      {w.penalty ? <span className="bad"> · −{w.penalty}</span> : null} · bank {mkr(w.bank_after)} ·{" "}
                      {num(w.expected_points)} xP <small>(utan byten {num(w.hold_points)})</small>
                    </span>
                  </div>
                  {w.out.length === 0 ? (
                    <p className="hint">
                      Inga byten – {w.free_before && w.free_before > 0 ? "spara gratisbytet" : "vänta på nästa gratisbyte"}.
                    </p>
                  ) : (
                    w.out.map((o, i) => {
                      const inId = w.in[i];
                      return (
                        <div key={o} className="swap">
                          <span className="out-name">
                            {players[o]?.name} <TrendArrow trend={plan.trends[o]} />
                          </span>
                          <span className="arrow">→</span>
                          <span className="in-name">
                            {players[inId]?.name} <TrendArrow trend={plan.trends[inId]} />{" "}
                            <small>
                              {players[inId]?.club} · {mkr(players[inId]?.price ?? 0)}
                            </small>
                          </span>
                        </div>
                      );
                    })
                  )}
                </div>
              ))}
            {tail.length > 0 && (
              <p className="hint">
                Efter planen: {tail.map((w) => `v.${w.gameweek} ${num(w.expected_points)} xP (utan byten ${num(w.hold_points)})`).join(" · ")}
              </p>
            )}
          </div>
          {first && first.out.length > 0 && (
            <div className="toolbar">
              <button className="small" onClick={() => onLoad(first.out, first.in)}>
                Ladda veckans byten i kalkylatorn
              </button>
            </div>
          )}
          <p className="hint">
            Bara veckans byten behöver göras nu. Kör planen igen nästa vecka, då har ny data kommit in och planen kan
            ändras. Planen räknar med dagens priser.
          </p>
        </>
      )}
    </section>
  );
}

/** Hur ett byte eller en plan ändrar värdet av kortplanen, per kort. */
function CardImpactView({ cards, netInclCards }: { cards: CardImpact | null; netInclCards: number }) {
  if (!cards) return null;
  const changed = Object.values(cards.per_card).filter((c) => Math.abs(c.change) >= 0.05);
  if (changed.length === 0) return null;
  const at = (x: { gameweek: number; gain: number } | null) => (x ? `v.${x.gameweek} ${signed(x.gain)}` : "inte i planen");
  return (
    <div className="card-impact">
      <p className="hint">
        Kortplanen {signed(cards.change)} xP ({num(cards.value_before)} → {num(cards.value_after)}) · netto inkl. kort{" "}
        <strong>{signed(netInclCards)} xP</strong>
      </p>
      <ul>
        {changed.map((c) => (
          <li key={c.name}>
            <span className={c.change < 0 ? "bad" : "good"}>{c.name}</span> {at(c.before)} → {at(c.after)}{" "}
            <small>({signed(c.change)})</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CardScheduleView({ schedule }: { schedule: CardScheduleItem[] }) {
  if (!schedule.length) return null;
  return (
    <p className="hint">
      Kort som planen räknar med: {schedule.map((c) => `v.${c.gameweek} ${c.name}`).join(" · ")}
    </p>
  );
}
