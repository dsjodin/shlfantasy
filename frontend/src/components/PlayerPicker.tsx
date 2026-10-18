import { useEffect, useMemo, useState } from "react";
import { mkr, num } from "../format";
import { useApp } from "../state";
import { POSITION_SINGULAR, type Player, type Position } from "../types";
import { ClubBadge, PosBadge, StatusChip } from "./PlayerBits";

interface Props {
  position: Position | null;
  title?: string;
  excludeIds: string[];
  maxPrice: number | null;
  clubCounts: Record<string, number>;
  onPick: (p: Player) => void;
  onClose: () => void;
}

type SortKey = "xp_horizon" | "xp_next" | "price" | "form" | "value" | "total_points";

const SORTS: Record<SortKey, { label: string; fn: (p: Player) => number }> = {
  xp_horizon: { label: "xP perioden", fn: (p) => p.xp_horizon },
  xp_next: { label: "xP nästa vecka", fn: (p) => p.xp_next },
  value: { label: "xP per Mkr", fn: (p) => (p.price ? p.xp_horizon / p.price : 0) },
  form: { label: "Form", fn: (p) => p.form },
  total_points: { label: "Totala poäng", fn: (p) => p.total_points },
  price: { label: "Pris", fn: (p) => p.price },
};

export function PlayerPicker({ position, title, excludeIds, maxPrice, clubCounts, onPick, onClose }: Props) {
  const { playerList } = useApp();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("xp_horizon");
  const [onlyAffordable, setOnlyAffordable] = useState(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const excluded = new Set(excludeIds);
    return playerList
      .filter((p) => (!position || p.position === position) && !excluded.has(p.id))
      .filter((p) => !q || p.name.toLowerCase().includes(q) || p.club.toLowerCase().includes(q))
      .map((p) => {
        let reason: string | null = null;
        if ((clubCounts[p.club] ?? 0) >= 3) reason = `Redan 3 från ${p.club}`;
        else if (maxPrice !== null && p.price > maxPrice + 1e-9) reason = `${mkr(p.price - maxPrice)} för dyr`;
        return { p, reason };
      })
      .filter((r) => !onlyAffordable || !r.reason)
      .sort((a, b) => SORTS[sort].fn(b.p) - SORTS[sort].fn(a.p))
      .slice(0, 150);
  }, [playerList, position, excludeIds, query, sort, clubCounts, maxPrice, onlyAffordable]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h3>{title ?? (position ? `Välj ${POSITION_SINGULAR[position]}` : "Välj spelare")}</h3>
          <button className="ghost" onClick={onClose} aria-label="Stäng">
            ✕
          </button>
        </div>
        <div className="picker-controls">
          <input autoFocus placeholder="Sök namn eller lag…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            {Object.entries(SORTS).map(([k, v]) => (
              <option key={k} value={k}>
                Sortera: {v.label}
              </option>
            ))}
          </select>
          <label className="check">
            <input type="checkbox" checked={onlyAffordable} onChange={(e) => setOnlyAffordable(e.target.checked)} />
            Bara möjliga
          </label>
        </div>
        {maxPrice !== null && <p className="hint">Du har {mkr(maxPrice)} att lägga på den här platsen.</p>}
        <div className="picker-list">
          {rows.map(({ p, reason }) => (
            <button key={p.id} className="pick" disabled={!!reason} onClick={() => onPick(p)}>
              <PosBadge pos={p.position} />
              <span className="pick-name">
                {p.name} <StatusChip status={p.status} />
                <small>
                  <ClubBadge club={p.club} /> {p.games_next} matcher nästa · form {num(p.form)} · {p.total_points} p
                  {reason && <em> · {reason}</em>}
                </small>
              </span>
              <span className="pick-price">{mkr(p.price)}</span>
              <span className="pick-xp">
                {num(SORTS[sort === "price" ? "xp_horizon" : sort].fn(p))}
                <small>{sort === "price" ? "xP" : SORTS[sort].label}</small>
              </span>
            </button>
          ))}
          {rows.length === 0 && <p className="empty">Inga spelare matchar.</p>}
        </div>
      </div>
    </div>
  );
}
