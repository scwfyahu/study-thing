import { useEffect, useState } from "react";
import { api } from "../api.js";
import { STATUS_LABEL } from "./NotebookView.jsx";

const fmtDate = (s) => {
  if (!s) return "";
  const d = new Date(s.replace(" ", "T"));
  if (isNaN(d)) return s;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

function Stat({ n, label, onClick }) {
  return (
    <button className="stat" onClick={onClick}>
      <span className="stat-n">{n}</span>
      <span className="stat-label">{label}</span>
    </button>
  );
}

export default function HomeView({ onOpenNotebook, onOpenSuggest, onOpenSchedule, onNewNotebook }) {
  const [data, setData] = useState(null);
  const [proc, setProc] = useState(null);

  const load = () => {
    api.home().then(setData).catch(() => {});
    api.processing().then(setProc).catch(() => {});
  };
  useEffect(load, []);
  useEffect(() => {
    const t = setInterval(() => {
      api.processing().then(setProc).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, []);

  if (!data) return <div className="loading">Loading…</div>;
  const t = data.totals || {};
  const empty = (t.notebooks || 0) === 0;

  return (
    <div className="home">
      <div className="nb-head">
        <div>
          <h2>Home</h2>
          <div className="topics-line">
            {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
          </div>
        </div>
      </div>

      {empty ? (
        <div className="empty" style={{ marginTop: "6vh" }}>
          <h2>Your classes, distilled to flashcards.</h2>
          <p>Create a notebook for each class, then drop in your lecture recordings.</p>
          <p className="hint">Noise gets cleaned (ffmpeg) → transcribed locally (whisper.cpp) → turned into flashcards (LLM).</p>
          <p style={{ marginTop: 12 }}>
            <button className="btn primary" onClick={onNewNotebook}>＋ New notebook</button>
          </p>
        </div>
      ) : (
        <>
          <div className="stat-row">
            <Stat n={t.notebooks} label="classes" onClick={() => {}} />
            <Stat n={t.recordings} label="recordings" />
            <Stat n={t.cards} label="flashcards" />
            <Stat n={t.decks} label="decks" />
            <Stat n={t.quizzes} label="quizzes" />
            <Stat n={t.inbox} label="inbox" onClick={t.inbox > 0 ? onOpenSuggest : undefined} />
          </div>

          {(t.inbox > 0) && (
            <div className="home-callout" onClick={onOpenSuggest} role="button">
              <span className="home-callout-n">{t.inbox}</span>
              &nbsp;transcription{t.inbox > 1 ? "s" : ""} waiting for assignment — review in the Suggest inbox →
            </div>
          )}

          {proc?.busy && (
            <div className="home-section">
              <h4>Processing</h4>
              <div className="progress"><div className="bar" style={{ width: `${Math.round((proc.progress || 0) * 100)}%` }} /></div>
              <div className="muted small-note">{proc.recordings} recording{proc.recordings > 1 ? "s" : ""} in the queue</div>
            </div>
          )}

          <div className="home-section">
            <div className="home-sec-head">
              <h4>Upcoming tests</h4>
              <button className="btn small" onClick={onOpenSchedule}>Quiz schedule</button>
            </div>
            {data.tests.length === 0 ? (
              <div className="muted small-note">No tests scheduled — scan recordings or add one in the quiz schedule.</div>
            ) : (
              <div className="home-list">
                {data.tests.map((x) => (
                  <div className="home-row" key={x.id}>
                    <span className="home-row-name" onClick={() => onOpenNotebook(x.nb_id)}>{x.title}</span>
                    <span className="muted small-note">{x.nb_name}</span>
                    <span className="spacer" />
                    {x.confirmed ? (
                      <span className="badge s-done">{x.test_date ? fmtDate(x.test_date) : "scheduled"}</span>
                    ) : (
                      <span className="badge">awaiting scope</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="home-section">
            <div className="home-sec-head">
              <h4>Recent recordings</h4>
            </div>
            <div className="home-list">
              {data.recent.map((r) => (
                <div className="home-row" key={r.id}>
                  <span className="home-row-name" onClick={() => r.nb_id && onOpenNotebook(r.nb_id)}>{r.original_name}</span>
                  {!r.nb_id && <span className="muted small-note">inbox</span>}
                  {r.nb_name && <span className="muted small-note">{r.nb_name}</span>}
                  <span className="spacer" />
                  <span className="muted small-note">{fmtDate(r.when_txt)}</span>
                  <span className={`badge s-${r.status}`}>{STATUS_LABEL[r.status] || r.status}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
