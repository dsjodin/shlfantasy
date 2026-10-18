import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Player, Status, Team } from "./types";

interface AppState {
  status: Status | null;
  players: Record<string, Player>;
  playerList: Player[];
  gameweeks: number[];
  horizon: number;
  setHorizon: (h: number) => void;
  team: Team | null;
  setTeam: (t: Team) => void;
  reload: () => Promise<void>;
  loading: boolean;
  error: string | null;
}

const Ctx = createContext<AppState | null>(null);

function readHorizon(): number {
  try {
    return Number(localStorage.getItem("horizon")) || 3;
  } catch {
    return 3;
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [playerList, setPlayerList] = useState<Player[]>([]);
  const [gameweeks, setGameweeks] = useState<number[]>([]);
  const [horizon, setHorizonState] = useState(readHorizon);
  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await api.status();
      setStatus(s);
      if (!s.loaded) {
        setError("Hämtar data från fantasy.shl.se och shl.se för första gången – sidan laddas om automatiskt…");
        setTimeout(() => void reload(), 5000);
        return;
      }
      const [p, t] = await Promise.all([api.players(horizon), api.team()]);
      setPlayerList(p.players);
      setGameweeks(p.gameweeks);
      setTeam(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [horizon]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setHorizon = (h: number) => {
    setHorizonState(h);
    try {
      localStorage.setItem("horizon", String(h));
    } catch {
      /* privat läge */
    }
  };

  const players = useMemo(() => Object.fromEntries(playerList.map((p) => [p.id, p])), [playerList]);

  return (
    <Ctx.Provider
      value={{ status, players, playerList, gameweeks, horizon, setHorizon, team, setTeam, reload, loading, error }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp utanför AppProvider");
  return ctx;
}
