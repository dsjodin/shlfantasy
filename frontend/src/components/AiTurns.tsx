import type { AiTurn } from "./AiStream";
import { Markdown } from "./Markdown";

export function AiTurns({ turns, hideFirstUser = false }: { turns: AiTurn[]; hideFirstUser?: boolean }) {
  return (
    <div className="turns">
      {turns.map((t, i) =>
        t.role === "user" ? (
          hideFirstUser && i === 0 ? null : (
            <div key={i} className="turn user">
              {t.text}
            </div>
          )
        ) : (
          <div key={i} className="turn assistant">
            {t.tools.length > 0 && (
              <div className="tools">
                {t.tools.map((label, j) => (
                  <span key={j} className="tool-chip">
                    {label}
                  </span>
                ))}
              </div>
            )}
            {t.text && <Markdown text={t.text} />}
            {t.pending && !t.text && <div className="thinking">Tänker…</div>}
            {t.pending && t.text && <span className="cursor" />}
            {t.sources && t.sources.length > 0 && (
              <div className="sources">
                <span>Källor:</span>
                {t.sources.map((s) => (
                  <a key={s.url} href={s.url} target="_blank" rel="noreferrer noopener">
                    {s.title}
                  </a>
                ))}
              </div>
            )}
            {t.error && <div className="alert error">{t.error}</div>}
          </div>
        ),
      )}
    </div>
  );
}
