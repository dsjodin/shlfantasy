import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setApiProfile, type Profile } from "./api";
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
  profiles: Profile[] | null;
  profile: Profile | null;
  selectProfile: (id: string | null) => void;
  createProfile: (name: string) => Promise<void>;
  renameProfile: (name: string) => Promise<void>;
  deleteProfile: () => Promise<void>;
}

const Ctx = createContext<AppState | null>(null);

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* privat läge */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [playerList, setPlayerList] = useState<Player[]>([]);
  const [gameweeks, setGameweeks] = useState<number[]>([]);
  const [horizon, setHorizonState] = useState(() => Number(readStored("horizon")) || 3);
  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [profileId, setProfileId] = useState<string | null>(null);

  // Vilken profil enheten använde senast sparas lokalt; själva lagen ligger på servern.
  const selectProfile = useCallback((id: string | null) => {
    setApiProfile(id);
    writeStored("profile", id);
    setTeam(null);
    setProfileId(id);
  }, []);

  useEffect(() => {
    api
      .profiles()
      .then(({ profiles: list }) => {
        setProfiles(list);
        const stored = readStored("profile");
        const match = list.find((p) => p.id === stored) ?? (list.length === 1 ? list[0] : null);
        selectProfile(match?.id ?? null);
      })
      .catch((e) => setError(String(e)));
  }, [selectProfile]);

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
      const [p, t] = await Promise.all([api.players(horizon), profileId ? api.team() : Promise.resolve(null)]);
      setPlayerList(p.players);
      setGameweeks(p.gameweeks);
      setTeam(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [horizon, profileId]);

  useEffect(() => {
    if (profiles !== null) void reload();
  }, [reload, profiles]);

  const setHorizon = (h: number) => {
    setHorizonState(h);
    writeStored("horizon", String(h));
  };

  const createProfile = async (name: string) => {
    const created = await api.createProfile(name);
    setProfiles((ps) => [...(ps ?? []), created].sort((a, b) => a.name.localeCompare(b.name, "sv")));
    selectProfile(created.id);
  };

  const renameProfile = async (name: string) => {
    if (!profileId) return;
    const renamed = await api.renameProfile(profileId, name);
    setProfiles((ps) => (ps ?? []).map((p) => (p.id === renamed.id ? renamed : p)));
  };

  const deleteProfile = async () => {
    if (!profileId) return;
    const { profiles: left } = await api.deleteProfile(profileId);
    setProfiles(left);
    selectProfile(null);
  };

  const players = useMemo(() => Object.fromEntries(playerList.map((p) => [p.id, p])), [playerList]);
  const profile = profiles?.find((p) => p.id === profileId) ?? null;

  return (
    <Ctx.Provider
      value={{
        status,
        players,
        playerList,
        gameweeks,
        horizon,
        setHorizon,
        team,
        setTeam,
        reload,
        loading,
        error,
        profiles,
        profile,
        selectProfile,
        createProfile,
        renameProfile,
        deleteProfile,
      }}
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
