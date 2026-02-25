export interface NewGameResponse {
  session_id: string;
  fen: string;
  status: string;
}

export interface ArrowData {
  orig: string;
  dest: string;
  brush: string;
}

export interface HighlightData {
  square: string;
  brush: string;
}

export interface CoachingData {
  quality: string;
  message: string;
  arrows: ArrowData[];
  highlights: HighlightData[];
  severity: string;
  debug_prompt?: string;
}

export interface MoveResponse {
  fen: string;
  player_move_san: string;
  opponent_move_uci: string | null;
  opponent_move_san: string | null;
  status: string;
  result: string | null;
  coaching: CoachingData | null;
}

const API_BASE = "/api";

export async function createGame(
  depth: number = 10,
  eloProfile: string = "intermediate",
  coachName: string = "Anna Cramling",
): Promise<NewGameResponse> {
  const res = await fetch(`${API_BASE}/game/new`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ depth, elo_profile: eloProfile, coach_name: coachName }),
  });
  if (!res.ok) {
    throw new Error(`Failed to create game: ${res.status}`);
  }
  return res.json();
}

export async function sendMove(
  sessionId: string,
  moveUci: string,
  verbosity: string = "normal",
): Promise<MoveResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const res = await fetch(`${API_BASE}/game/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, move: moveUci, verbosity }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(detail.detail || `Move failed: ${res.status}`);
    }
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}
