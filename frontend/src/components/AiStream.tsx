import { useCallback, useRef, useState } from "react";
import { streamChat } from "../api";
import type { ChatEvent } from "../types";

export interface AiTurn {
  role: "user" | "assistant";
  text: string;
  tools: string[];
  sources?: { url: string; title: string }[];
  error?: string;
  pending?: boolean;
}

/** Hanterar en strömmande AI-konversation (används av chatten och bytesgranskningen). */
export function useAiConversation() {
  const [turns, setTurns] = useState<AiTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const run = useCallback(async (path: string, body: Record<string, unknown>, userText: string | null) => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setBusy(true);
    setTurns((t) => [
      ...t,
      ...(userText ? [{ role: "user" as const, text: userText, tools: [] }] : []),
      { role: "assistant", text: "", tools: [], pending: true },
    ]);
    const update = (fn: (turn: AiTurn) => AiTurn) =>
      setTurns((t) => [...t.slice(0, -1), fn(t[t.length - 1])]);
    const onEvent = (e: ChatEvent) => {
      if (e.type === "conversation") conversationId.current = e.id;
      else if (e.type === "text") update((turn) => ({ ...turn, text: turn.text + e.text }));
      else if (e.type === "tool") update((turn) => ({ ...turn, tools: [...turn.tools, e.label] }));
      else if (e.type === "sources")
        update((turn) => {
          const known = new Set((turn.sources ?? []).map((s) => s.url));
          return { ...turn, sources: [...(turn.sources ?? []), ...e.sources.filter((s) => !known.has(s.url))] };
        });
      else if (e.type === "error") update((turn) => ({ ...turn, error: e.message }));
      else if (e.type === "done") update((turn) => ({ ...turn, pending: false }));
    };
    try {
      await streamChat(path, { ...body, conversation_id: conversationId.current }, onEvent, ctrl.signal);
    } catch (err) {
      if (!ctrl.signal.aborted) update((turn) => ({ ...turn, error: String(err) }));
    } finally {
      update((turn) => ({ ...turn, pending: false }));
      setBusy(false);
    }
  }, []);

  const reset = useCallback(() => {
    abort.current?.abort();
    conversationId.current = null;
    setTurns([]);
    setBusy(false);
  }, []);

  return { turns, busy, run, reset, conversationId };
}
