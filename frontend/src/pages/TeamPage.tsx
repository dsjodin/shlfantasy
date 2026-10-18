import { useEffect, useMemo, useState } from "react";
import { api, type TeamInput } from "../api";
import { PlayerPicker } from "../components/PlayerPicker";
import { ProfileSettings } from "../components/Profiles";
import { PlayerRow } from "../components/PlayerBits";
import { mkr, num } from "../format";
import { useApp } from "../state";
import { POSITIONS, POSITION_NAMES, POSITION_SINGULAR, SQUAD, type Lineup, type Position, type Team } from "../types";

export function TeamPage() {
  const { team, setTeam, players, status, horizon } = useApp();
  const [draft, setDraft] = useState<TeamInput | null>(null);
  const [preview, setPreview] = useState<Team | null>(null);
  const [picker, setPicker] = useState<{ pos: Position; replace?: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (team && !draft) {
      setDraft({
        player_ids: team.player_ids,
        bank: team.bank,
        free_transfers: team.free_transfers,
        used_cards: team.used_cards,
      });
    }
  }, [team, draft]);

  const dirty = useMemo(
    () =>
      !!draft &&
      !!team &&
      JSON.stringify(draft) !==
        JSON.stringify({
          player_ids: team.player_ids,
          bank: team.bank,
          free_transfers: team.free_transfers,
          used_cards: team.used_cards,
        }),
    [draft, team],
  );

  // Live-validering av utkastet
  useEffect(() => {
    if (!draft) return;
    const timer = setTimeout(() => {
      api.validateTeam(draft).then(setPreview).catch(() => undefined);
    }, 250);
    return () => clearTimeout(timer);
  }, [draft]);

  if (!draft) return <p className="empty">Laddar…</p>;

  const view = preview ?? team;
  const squad = draft.player_ids.map((id) => players[id]).filter(Boolean);
  const clubCounts: Record<string, number> = {};
  squad.forEach((p) => (clubCounts[p.club] = (clubCounts[p.club] ?? 0) + 1));
  const squadValue = squad.reduce((s, p) => s + p.price, 0);

  const update = (patch: Partial<TeamInput>) => setDraft({ ...draft, ...patch });

  const pick = (id: string) => {
    if (!picker) return;
    const ids = picker.replace
      ? draft.player_ids.map((x) => (x === picker.replace ? id : x))
      : [...draft.player_ids, id];
    update({ player_ids: ids });
    setPicker(null);
  };

  const save = async () => {
    setSaving(true);
    try {
      const saved = await api.saveTeam(draft);
      setTeam(saved);
      setDraft({ player_ids: saved.player_ids, bank: saved.bank, free_transfers: saved.free_transfers, used_cards: saved.used_cards });
      setMessage("Laget sparat.");
    } catch (e) {
      setMessage(`Kunde inte spara: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
      setTimeout(() => setMessage(null), 3000);
    }
  };

  const buildOptimal = async () => {
    if (draft.player_ids.length && !confirm("Ersätta hela laget med modellens optimala lag för 100 Mkr?")) return;
    setSaving(true);
    try {
      const result = await api.build(horizon);
      update({ player_ids: result.new_player_ids, bank: result.bank_after });
    } catch (e) {
      setMessage(String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggleCard = (key: string) =>
    update({
      used_cards: draft.used_cards.includes(key)
        ? draft.used_cards.filter((c) => c !== key)
        : [...draft.used_cards, key],
    });

  return (
    <div className="page">
      <section className="card summary">
        <div className="stat">
          <span>Lagvärde</span>
          <strong>{mkr(squadValue)}</strong>
        </div>
        <label className="stat">
          <span>Kvar i banken (Mkr)</span>
          <input
            type="number"
            step="0.1"
            value={draft.bank}
            onChange={(e) => update({ bank: Number(e.target.value) })}
          />
        </label>
        <label className="stat">
          <span>Gratis byten</span>
          <select value={draft.free_transfers} onChange={(e) => update({ free_transfers: Number(e.target.value) })}>
            {[0, 1, 2].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <div className="stat">
          <span>Totalt</span>
          <strong>{mkr(squadValue + draft.bank)}</strong>
        </div>
        <div className="stat">
          <span>xP vecka {status?.next_gameweek ?? "–"}</span>
          <strong>{view?.lineup ? num(view.lineup.expected_points) : "–"}</strong>
        </div>
      </section>

      <div className="toolbar">
        <button className="primary" disabled={!dirty || saving} onClick={save}>
          {dirty ? "Spara laget" : "Sparat"}
        </button>
        {dirty && team && (
          <button
            className="ghost"
            onClick={() =>
              setDraft({ player_ids: team.player_ids, bank: team.bank, free_transfers: team.free_transfers, used_cards: team.used_cards })
            }
          >
            Ångra ändringar
          </button>
        )}
        <button className="ghost" disabled={saving} onClick={buildOptimal}>
          Föreslå optimalt lag (100 Mkr)
        </button>
        {message && <span className="hint">{message}</span>}
      </div>

      {draft.player_ids.length === 0 && (
        <div className="alert info">
          Lägg in de 15 spelare du har i Fantasy SHL och hur mycket du har kvar i banken. Det behöver bara göras
          en gång – när du sedan gör byten här uppdateras laget automatiskt.
        </div>
      )}

      {view && view.issues.length > 0 && (
        <ul className="issues">
          {view.issues.map((i, k) => (
            <li key={k} className={i.level}>
              {i.message}
            </li>
          ))}
        </ul>
      )}

      <div className="two-col">
        <section className="card">
          <h2>Trupp</h2>
          {POSITIONS.map((pos) => {
            const inPos = squad.filter((p) => p.position === pos);
            const empty = SQUAD[pos] - inPos.length;
            return (
              <div key={pos} className="pos-group">
                <h3>
                  {POSITION_NAMES[pos]} <small>{inPos.length}/{SQUAD[pos]}</small>
                </h3>
                {inPos.map((p) => (
                  <PlayerRow
                    key={p.id}
                    player={p}
                    actions={
                      <>
                        <button className="small ghost" onClick={() => setPicker({ pos, replace: p.id })}>
                          Byt
                        </button>
                        <button
                          className="small ghost"
                          aria-label={`Ta bort ${p.name}`}
                          onClick={() => update({ player_ids: draft.player_ids.filter((x) => x !== p.id) })}
                        >
                          ✕
                        </button>
                      </>
                    }
                  />
                ))}
                {Array.from({ length: Math.max(0, empty) }).map((_, k) => (
                  <button key={k} className="slot" onClick={() => setPicker({ pos })}>
                    + Lägg till {POSITION_SINGULAR[pos]}
                  </button>
                ))}
              </div>
            );
          })}
        </section>

        <div className="stack">
          {view?.lineup && <LineupCard lineup={view.lineup} />}
          <section className="card">
            <h2>Använda coachkort</h2>
            <div className="cards-used">
              {Object.entries(status?.rules.cards ?? {}).map(([key, name]) => (
                <label key={key} className="check">
                  <input type="checkbox" checked={draft.used_cards.includes(key)} onChange={() => toggleCard(key)} />
                  {name}
                </label>
              ))}
            </div>
          </section>
        </div>
      </div>

      <ProfileSettings />

      {picker && (
        <PlayerPicker
          position={picker.pos}
          excludeIds={draft.player_ids}
          maxPrice={null}
          clubCounts={Object.fromEntries(
            Object.entries(clubCounts).map(([c, n]) => [
              c,
              picker.replace && players[picker.replace]?.club === c ? n - 1 : n,
            ]),
          )}
          onPick={(p) => pick(p.id)}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  );
}

export function LineupCard({ lineup }: { lineup: Lineup }) {
  const { players } = useApp();
  const badge = (id: string) => (id === lineup.captain ? "C" : id === lineup.vice_captain ? "A" : undefined);
  const group = (title: string, ids: string[]) => (
    <div className="pos-group">
      <h3>{title}</h3>
      {ids
        .map((id) => players[id])
        .filter(Boolean)
        .map((p) => (
          <PlayerRow key={p.id} player={p} badge={badge(p.id)} />
        ))}
    </div>
  );
  return (
    <section className="card">
      <h2>
        Föreslagen laguttagning v.{lineup.gameweek} <small>{num(lineup.expected_points)} xP</small>
      </h2>
      {group("Förstafemman + målvakt", lineup.first_five)}
      {group("Andrafemman", lineup.second_five)}
      {group("Bänk", lineup.bench)}
      <p className="hint">C = kapten, A = assisterande kapten (näst högst xP).</p>
    </section>
  );
}
