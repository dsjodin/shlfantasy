export type Position = "GK" | "D" | "C" | "F";

export const POSITIONS: Position[] = ["GK", "D", "C", "F"];

export const POSITION_NAMES: Record<Position, string> = {
  GK: "Målvakter",
  D: "Backar",
  C: "Centrar",
  F: "Forwards",
};

export const POSITION_SINGULAR: Record<Position, string> = {
  GK: "målvakt",
  D: "back",
  C: "center",
  F: "forward",
};

export const SQUAD: Record<Position, number> = { GK: 2, D: 5, C: 3, F: 5 };

export interface Player {
  id: string;
  name: string;
  club: string;
  position: Position;
  status: "active" | "injured" | "unavailable";
  price: number;
  ownership: number;
  games_played: number;
  total_points: number;
  ppg: number;
  form: number;
  age: number | null;
  xp_per_game: number;
  play_rate: number;
  xp_next: number;
  xp_horizon: number;
  games_next: number;
  xp: Record<string, number>;
  games: Record<string, number>;
  breakdown?: Record<string, number>;
  history?: { gameweek: number; games: number; points: number }[];
  fixtures?: Record<string, string[]>;
}

export interface Issue {
  level: "error" | "warning";
  message: string;
}

export interface Lineup {
  gameweek: number;
  starters: string[];
  bench: string[];
  first_five: string[];
  second_five: string[];
  captain: string | null;
  vice_captain: string | null;
  expected_points: number;
}

export interface Team {
  player_ids: string[];
  bank: number;
  free_transfers: number;
  used_cards: string[];
  valid: boolean;
  issues: Issue[];
  squad_value: number;
  lineup: Lineup | null;
}

export interface Status {
  loaded: boolean;
  season: number;
  fetched_at: string | null;
  errors: string[];
  players: number;
  games: number;
  birthdates: number;
  next_gameweek: number | null;
  current_gameweek: number | null;
  ai_enabled: boolean;
  ai_model: string | null;
  rules: { cards: Record<string, string> };
}

export interface Evaluation {
  valid: boolean;
  issues: Issue[];
  new_player_ids: string[];
  sold_value: number;
  bought_value: number;
  bank_before: number;
  bank_after: number;
  transfers: number;
  free_transfers: number;
  penalty: number;
  gameweeks: number[];
  xp_next_before: number;
  xp_next_after: number;
  xp_horizon_before: number;
  xp_horizon_after: number;
  xp_gain_horizon: number;
  net_gain: number;
  per_week: { gameweek: number; before: number; after: number }[];
}

export interface Suggestion extends Evaluation {
  out: string[];
  in: string[];
}

export interface Alternative {
  player_id: string;
  xp_gain: number;
  xp_horizon: number;
  bank_after: number;
}

export interface CardWeek {
  gameweek: number;
  start: string | null;
  end: string | null;
  expected_points: number;
  squad_games: number;
  cards: Record<string, { name: string; gain: number | null; used: boolean }>;
  juniors: string[];
  veterans: string[];
}

export interface Gameweek {
  number: number;
  start: string;
  end: string;
  status: "upcoming" | "ongoing" | "completed";
  games_per_club: Record<string, number>;
}

export interface Fixture {
  opponent: string;
  home: boolean;
  date: string;
  played: boolean;
}

export type ChatEvent =
  | { type: "conversation"; id: string }
  | { type: "text"; text: string }
  | { type: "tool"; name: string; label: string }
  | { type: "error"; message: string }
  | { type: "done" };
