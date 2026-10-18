import { useEffect, useState } from "react";
import { api } from "./api";
import { dateTime } from "./format";
import { ProfileMenu, ProfilePicker } from "./components/Profiles";
import { AdvisorPage } from "./pages/AdvisorPage";
import { PlannerPage } from "./pages/PlannerPage";
import { PlayersPage } from "./pages/PlayersPage";
import { TeamPage } from "./pages/TeamPage";
import { TransfersPage } from "./pages/TransfersPage";
import { useApp } from "./state";

const TABS = {
  team: { label: "Mitt lag", el: TeamPage },
  transfers: { label: "Byten", el: TransfersPage },
  planner: { label: "Kapten & kort", el: PlannerPage },
  players: { label: "Spelare", el: PlayersPage },
  advisor: { label: "AI-rådgivare", el: AdvisorPage },
} as const;

type TabKey = keyof typeof TABS;

function readTab(): TabKey {
  const hash = window.location.hash.slice(1);
  return hash in TABS ? (hash as TabKey) : "team";
}

export function App() {
  const { status, horizon, setHorizon, gameweeks, loading, error, reload, profile, profiles } = useApp();
  const [tab, setTab] = useState<TabKey>(readTab);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const onHash = () => setTab(readTab());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await api.refresh();
      await reload();
    } finally {
      setRefreshing(false);
    }
  };

  const Page = TABS[tab].el;

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo">🏒</span>
          <div>
            <h1>SHL Fantasy-hjälpen</h1>
            <small>
              {status?.next_gameweek ? `Nästa matchvecka: ${status.next_gameweek}` : ""}
              {status?.fetched_at ? ` · data ${dateTime(status.fetched_at)}` : ""}
            </small>
          </div>
        </div>
        <div className="header-controls">
          <ProfileMenu />
          <label title="Hur många veckor framåt xP och optimering räknar på">
            Period{" "}
            <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  {n} {n === 1 ? "vecka" : "veckor"}
                </option>
              ))}
            </select>
          </label>
          <button className="ghost small" onClick={refresh} disabled={refreshing}>
            {refreshing ? "Hämtar…" : "Uppdatera data"}
          </button>
        </div>
      </header>
      <nav>
        {(Object.keys(TABS) as TabKey[]).map((key) => (
          <a key={key} href={`#${key}`} className={tab === key ? "active" : ""}>
            {TABS[key].label}
          </a>
        ))}
      </nav>
      <main>
        {status?.errors.map((e) => (
          <div key={e} className="alert warning">
            Datakälla: {e}
          </div>
        ))}
        {error ? (
          <div className="alert error">{error}</div>
        ) : profiles === null || (loading && !status) ? (
          <p className="empty">Laddar…</p>
        ) : !profile ? (
          <ProfilePicker />
        ) : (
          <Page key={profile.id} />
        )}
      </main>
      <footer>
        Data från fantasy.shl.se och shl.se. xP = förväntade poäng enligt en enkel statistisk modell
        {gameweeks.length ? ` (veckor ${gameweeks.join(", ")})` : ""}. Inofficiellt verktyg.
      </footer>
    </div>
  );
}
