import type {
  Alternative,
  CardWeek,
  ChatEvent,
  Evaluation,
  Fixture,
  Gameweek,
  Player,
  Status,
  Suggestion,
  Team,
} from "./types";

let currentProfile: string | null = null;

/** Vald profil skickas med i varje anrop så att servern vet vems lag det gäller. */
export function setApiProfile(id: string | null) {
  currentProfile = id;
}

function headers(json: boolean): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (currentProfile) h["X-Profile"] = currentProfile;
  return h;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: headers(!!body),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* inget JSON-svar */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface TeamInput {
  player_ids: string[];
  bank: number;
  free_transfers: number;
  used_cards: string[];
}

export interface TransferInput {
  out: string[];
  in: string[];
  horizon: number;
  free_card?: boolean;
}

export interface Profile {
  id: string;
  name: string;
}

export const api = {
  profiles: () => request<{ profiles: Profile[] }>("GET", "/api/profiles"),
  createProfile: (name: string) => request<Profile>("POST", "/api/profiles", { name }),
  renameProfile: (id: string, name: string) => request<Profile>("PATCH", `/api/profiles/${id}`, { name }),
  deleteProfile: (id: string) => request<{ profiles: Profile[] }>("DELETE", `/api/profiles/${id}`),
  status: () => request<Status>("GET", "/api/status"),
  refresh: () => request<Status>("POST", "/api/refresh"),
  players: (horizon: number) =>
    request<{ gameweeks: number[]; players: Player[] }>("GET", `/api/players?horizon=${horizon}`),
  player: (id: string) => request<Player>("GET", `/api/players/${id}?horizon=4`),
  gameweeks: () =>
    request<{ next_gameweek: number | null; gameweeks: Gameweek[] }>("GET", "/api/gameweeks"),
  fixtures: (weeks: number) =>
    request<{ gameweeks: { number: number; start: string; end: string }[]; clubs: Record<string, Record<string, Fixture[]>> }>(
      "GET",
      `/api/fixtures?weeks=${weeks}`,
    ),
  team: () => request<Team>("GET", "/api/team"),
  saveTeam: (team: TeamInput) => request<Team>("PUT", "/api/team", team),
  validateTeam: (team: TeamInput) => request<Team>("POST", "/api/team/validate", team),
  cards: (weeks: number) => request<{ weeks: CardWeek[] }>("GET", `/api/cards?weeks=${weeks}`),
  evaluate: (t: TransferInput) => request<Evaluation>("POST", "/api/transfers/evaluate", t),
  apply: (t: TransferInput) => request<Team>("POST", "/api/transfers/apply", t),
  suggest: (opts: { horizon: number; max_transfers: number; free_card: boolean; keep: string[]; avoid: string[] }) =>
    request<{ options: Suggestion[] }>("POST", "/api/transfers/suggest", opts),
  build: (horizon: number, budget = 100) =>
    request<Suggestion>("POST", "/api/transfers/build", { horizon, budget }),
  alternatives: (id: string, horizon: number) =>
    request<{ options: Alternative[] }>("GET", `/api/transfers/alternatives/${id}?horizon=${horizon}&limit=8`),
};

/** Läser en SSE-ström från ett POST-anrop och anropar onEvent för varje händelse. */
export async function streamChat(
  path: string,
  body: unknown,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignorera */
    }
    onEvent({ type: "error", message: String(detail) });
    onEvent({ type: "done" });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as ChatEvent);
      }
    }
  }
}
