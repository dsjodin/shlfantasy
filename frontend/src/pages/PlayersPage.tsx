import { useMemo, useState } from "react";
import { ModelQuality } from "../components/ModelQuality";
import { PlayerDetail } from "../components/PlayerDetail";
import { ClubBadge, PosBadge, StatusChip } from "../components/PlayerBits";
import { num } from "../format";
import { useApp } from "../state";
import { POSITIONS, type Player } from "../types";

type Col = { key: string; label: string; title?: string; value: (p: Player) => number | string; digits?: number };

const COLUMNS: Col[] = [
  { key: "price", label: "Pris", value: (p) => p.price, digits: 1 },
  { key: "total_points", label: "Poäng", value: (p) => p.total_points, digits: 0 },
  { key: "games_played", label: "M", title: "Spelade matcher", value: (p) => p.games_played, digits: 0 },
  { key: "ppg", label: "P/M", title: "Poäng per match", value: (p) => p.ppg },
  { key: "form", label: "Form", title: "Snitt senaste 5 lagmatcher", value: (p) => p.form },
  { key: "games_next", label: "M nästa", title: "Matcher nästa vecka", value: (p) => p.games_next, digits: 0 },
  { key: "xp_next", label: "xP nästa", title: "Förväntade poäng nästa vecka", value: (p) => p.xp_next },
  { key: "xp_horizon", label: "xP period", title: "Förväntade poäng över vald period", value: (p) => p.xp_horizon },
  { key: "value", label: "xP/Mkr", title: "Förväntade poäng per miljon", value: (p) => (p.price ? p.xp_horizon / p.price : 0), digits: 2 },
  { key: "ownership", label: "Ägd %", value: (p) => p.ownership },
];

export function PlayersPage() {
  const { playerList, team } = useApp();
  const [query, setQuery] = useState("");
  const [pos, setPos] = useState<string>("");
  const [club, setClub] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [onlyActive, setOnlyActive] = useState(true);
  const [sort, setSort] = useState<{ key: string; desc: boolean }>({ key: "xp_horizon", desc: true });
  const [selected, setSelected] = useState<string | null>(null);

  const clubs = useMemo(() => [...new Set(playerList.map((p) => p.club))].sort(), [playerList]);
  const mine = new Set(team?.player_ids ?? []);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const col = COLUMNS.find((c) => c.key === sort.key);
    return playerList
      .filter((p) => !pos || p.position === pos)
      .filter((p) => !club || p.club === club)
      .filter((p) => !maxPrice || p.price <= Number(maxPrice))
      .filter((p) => !onlyActive || p.status === "active")
      .filter((p) => !q || p.name.toLowerCase().includes(q))
      .sort((a, b) => {
        const va = col ? col.value(a) : a.name;
        const vb = col ? col.value(b) : b.name;
        const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb), "sv");
        return sort.desc ? -cmp : cmp;
      });
  }, [playerList, query, pos, club, maxPrice, onlyActive, sort]);

  const header = (key: string, label: string, title?: string) => (
    <th
      key={key}
      title={title}
      className={sort.key === key ? "sorted" : ""}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))}
    >
      {label}
      {sort.key === key ? (sort.desc ? " ▾" : " ▴") : ""}
    </th>
  );

  return (
    <div className="page">
      <div className="filters">
        <input placeholder="Sök spelare…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={pos} onChange={(e) => setPos(e.target.value)}>
          <option value="">Alla positioner</option>
          {POSITIONS.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
        <select value={club} onChange={(e) => setClub(e.target.value)}>
          <option value="">Alla lag</option>
          {clubs.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <input
          type="number"
          step="0.5"
          placeholder="Maxpris"
          value={maxPrice}
          onChange={(e) => setMaxPrice(e.target.value)}
          className="narrow"
        />
        <label className="check">
          <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} /> Bara
          tillgängliga
        </label>
        <span className="hint">{rows.length} spelare</span>
      </div>
      <div className="table-wrap">
        <table className="players">
          <thead>
            <tr>
              {header("name", "Spelare")}
              <th>Lag</th>
              <th>Pos</th>
              {COLUMNS.map((c) => header(c.key, c.label, c.title))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className={mine.has(p.id) ? "mine" : ""} onClick={() => setSelected(p.id)}>
                <td className="name">
                  {p.name} <StatusChip status={p.status} />
                </td>
                <td>
                  <ClubBadge club={p.club} />
                </td>
                <td>
                  <PosBadge pos={p.position} />
                </td>
                {COLUMNS.map((c) => {
                  const v = c.value(p);
                  return <td key={c.key}>{typeof v === "number" ? num(v, c.digits ?? 1) : v}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">Markerade rader finns i ditt lag. Klicka på en spelare för detaljer.</p>
      <ModelQuality />
      {selected && <PlayerDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
