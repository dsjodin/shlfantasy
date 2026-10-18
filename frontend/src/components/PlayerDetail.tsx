import { useEffect, useState } from "react";
import { api } from "../api";
import { mkr, num } from "../format";
import type { Player } from "../types";
import { ClubBadge, PosBadge, StatusChip } from "./PlayerBits";

const BREAKDOWN_LABELS: Record<string, string> = {
  goals_points: "Mål",
  assists_points: "Assist",
  game_winning_goals_points: "Matchavgörande",
  shorthanded_goals_points: "Mål i boxplay",
  plus_minus_points: "Plus/minus",
  time_on_ice_points: "Istid",
  shots_on_goal_points: "Skott",
  faceoffs_won_points: "Tekningar",
  blocked_shots_points: "Blockerade skott",
  penalty_minutes_points: "Utvisningar",
  hits_points: "Tacklingar",
  saves_points: "Räddningar",
  goals_against_points: "Insläppta mål",
  shutouts_points: "Hållna nollor",
  wins_points: "Vinster",
  overtime_wins_points: "Vinster förl.",
  overtime_losses_points: "Förluster förl.",
  goalkeeper_appearances_points: "Matcher (MV)",
  other_points: "Övrigt",
};

export function PlayerDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const [p, setP] = useState<Player | null>(null);
  useEffect(() => {
    api.player(id).then(setP).catch(() => undefined);
  }, [id]);

  const maxPts = Math.max(1, ...(p?.history ?? []).map((h) => h.points));
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        {!p ? (
          <p className="empty">Laddar…</p>
        ) : (
          <>
            <div className="modal-head">
              <h3>
                <PosBadge pos={p.position} /> {p.name} <StatusChip status={p.status} />
              </h3>
              <button className="ghost" onClick={onClose} aria-label="Stäng">
                ✕
              </button>
            </div>
            <p className="hint">
              <ClubBadge club={p.club} /> {mkr(p.price)} · {p.age ? `${p.age} år · ` : ""}ägd av {num(p.ownership)} %
            </p>
            <div className="summary mini">
              <div className="stat">
                <span>Poäng</span>
                <strong>{p.total_points}</strong>
              </div>
              <div className="stat">
                <span>Per match</span>
                <strong>{num(p.ppg)}</strong>
              </div>
              <div className="stat">
                <span>Form</span>
                <strong>{num(p.form)}</strong>
              </div>
              <div className="stat">
                <span>Speltid</span>
                <strong>{Math.round(p.play_rate * 100)} %</strong>
              </div>
              <div className="stat">
                <span>xP/match</span>
                <strong>{num(p.xp_per_game)}</strong>
              </div>
            </div>
            <h4>Poäng per matchvecka</h4>
            <div className="history">
              {(p.history ?? []).map((h) => (
                <div key={h.gameweek} className="hbar" title={`${h.points} p på ${h.games} matcher`}>
                  <div style={{ height: `${(Math.max(h.points, 0) / maxPts) * 100}%` }} />
                  <span>{h.points}</span>
                  <small>v{h.gameweek}</small>
                </div>
              ))}
            </div>
            <h4>Kommande veckor</h4>
            <table className="mini-table">
              <tbody>
                {Object.entries(p.fixtures ?? {}).map(([gw, games]) => (
                  <tr key={gw}>
                    <td>v.{gw}</td>
                    <td>{games.length ? games.join(", ") : <em>Inga matcher</em>}</td>
                    <td className="num">{num(p.xp[gw] ?? 0)} xP</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h4>Poängfördelning säsongen</h4>
            <div className="breakdown">
              {Object.entries(p.breakdown ?? {}).map(([k, v]) => (
                <span key={k} className={v < 0 ? "neg" : ""}>
                  {BREAKDOWN_LABELS[k] ?? k}: <strong>{v}</strong>
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
