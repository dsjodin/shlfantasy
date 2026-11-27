import { STATUS_LABELS, minutes, mkr, num, signed } from "../format";
import type { Player, Trend } from "../types";

const TREND_ICON = { up: "▲", down: "▼", flat: "▬" } as const;

/** Liten pil som visar om formen pekar uppåt eller nedåt. */
export function TrendArrow({ trend }: { trend?: Trend }) {
  if (!trend) return null;
  const title =
    trend.weeks === 0
      ? trend.reason
      : `${trend.reason}. Senaste veckorna ${num(trend.recent_ppg)} p/match mot ${num(trend.season_ppg)} för säsongen ` +
        `(${signed(trend.ppg_delta)}). Speltid ${Math.round(trend.recent_play_rate * 100)} % mot ` +
        `${Math.round(trend.season_play_rate * 100)} %.` +
        (trend.season_toi && trend.recent_toi
          ? ` Istid ${minutes(trend.recent_toi)} per match mot ${minutes(trend.season_toi)}.`
          : "");
  return (
    <span className={`trend trend-${trend.direction}`} title={title} aria-label={title}>
      {TREND_ICON[trend.direction]}
    </span>
  );
}

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
          <ClubBadge club={player.club} /> {mkr(player.price)} · {player.games_next} m · form {num(player.form)}{" "}
          <TrendArrow trend={player.trend} />
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
