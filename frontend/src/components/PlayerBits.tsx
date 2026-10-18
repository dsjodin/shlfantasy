import { STATUS_LABELS, mkr, num } from "../format";
import type { Player } from "../types";

export function StatusChip({ status }: { status: Player["status"] }) {
  if (status === "active") return null;
  return <span className={`chip chip-${status}`}>{STATUS_LABELS[status]}</span>;
}

export function ClubBadge({ club }: { club: string }) {
  return <span className="club">{club}</span>;
}

export function PosBadge({ pos }: { pos: string }) {
  return <span className={`pos pos-${pos}`}>{pos}</span>;
}

interface RowProps {
  player: Player;
  badge?: string;
  actions?: React.ReactNode;
  muted?: boolean;
  onClick?: () => void;
}

export function PlayerRow({ player, badge, actions, muted, onClick }: RowProps) {
  return (
    <div className={`prow ${muted ? "muted" : ""} ${onClick ? "clickable" : ""}`} onClick={onClick}>
      <PosBadge pos={player.position} />
      <div className="prow-main">
        <div className="prow-name">
          {player.name}
          {badge && <span className="cap">{badge}</span>}
          <StatusChip status={player.status} />
        </div>
        <div className="prow-meta">
          <ClubBadge club={player.club} /> {mkr(player.price)} · {player.games_next} m · form {num(player.form)}
        </div>
      </div>
      <div className="prow-xp" title="Förväntade poäng nästa vecka">
        {num(player.xp_next)}
        <small>xP</small>
      </div>
      {actions && <div className="prow-actions" onClick={(e) => e.stopPropagation()}>{actions}</div>}
    </div>
  );
}
