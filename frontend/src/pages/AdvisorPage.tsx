import { useEffect, useRef, useState } from "react";
import { useAiConversation } from "../components/AiStream";
import { AiTurns } from "../components/AiTurns";
import { useApp } from "../state";

const STARTERS = [
  "Vilket byte borde jag göra inför nästa matchvecka?",
  "Vem ska vara kapten och assisterande kapten?",
  "När lönar det sig att spela mina coachkort?",
  "Vilka spelare i mitt lag är svagast just nu, och vad finns det för bättre alternativ?",
  "Hitta billiga backar med bra form som kan frigöra budget.",
];

export function AdvisorPage() {
  const { status } = useApp();
  const ai = useAiConversation();
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [ai.turns]);

  if (!status?.ai_enabled) {
    return (
      <div className="alert info">
        AI-rådgivaren är inte aktiverad. Lägg till din Claude API-nyckel som <code>ANTHROPIC_API_KEY</code> i filen{" "}
        <code>.env</code> och starta om appen. Nyckeln skapas på console.anthropic.com.
      </div>
    );
  }

  const send = (text: string) => {
    if (!text.trim() || ai.busy) return;
    void ai.run("/api/ai/chat", { message: text }, text);
    setInput("");
  };

  return (
    <div className="page chat-page">
      {ai.turns.length === 0 ? (
        <div className="starters">
          <p>
            Fråga om byten, kapten eller coachkort. AI:n räknar med verklig data och samma regelmotor som resten av
            appen, och säger ifrån om den tycker att det finns bättre val.
          </p>
          {STARTERS.map((s) => (
            <button key={s} className="starter" onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      ) : (
        <AiTurns turns={ai.turns} />
      )}
      <div ref={endRef} />
      <form
        className="chat-input sticky"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        {ai.turns.length > 0 && (
          <button type="button" className="ghost" onClick={ai.reset} title="Ny konversation">
            Ny
          </button>
        )}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Skriv en fråga…"
          disabled={ai.busy}
          autoFocus
        />
        <button className="primary" disabled={ai.busy || !input.trim()}>
          Skicka
        </button>
      </form>
      <p className="hint center">Modell: {status.ai_model}</p>
    </div>
  );
}
