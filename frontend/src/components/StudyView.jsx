import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const RATINGS = [
  { key: "again", label: "Again", kbd: "1", cls: "bad", hint: "didn't know — comes back today" },
  { key: "hard", label: "Hard", kbd: "2", cls: "", hint: "barely knew it" },
  { key: "good", label: "Good", kbd: "3", cls: "", hint: "knew it" },
  { key: "easy", label: "Easy", kbd: "4", cls: "good", hint: "too easy — skip ahead" },
];

export default function StudyView({ notebookId, recordingId, topic, title, onClose }) {
  const [queue, setQueue] = useState(null);
  const [idx, setIdx] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [err, setErr] = useState("");
  const [doneCount, setDoneCount] = useState(0);

  useEffect(() => {
    api
      .study(notebookId, recordingId, topic)
      .then((q) => setQueue(q))
      .catch((e) => setErr(e.message));
  }, [notebookId, recordingId, topic]);

  const rate = async (rating) => {
    if (!queue) return;
    const card = queue.cards[idx];
    try {
      await api.rate(card.id, rating);
    } catch (e) {
      setErr(e.message);
      return;
    }
    setDoneCount((d) => d + 1);
    const next = queue.cards.filter((_, i) => i !== idx);
    setQueue({ ...queue, cards: next });
    setIdx(0);
    setFlipped(false);
  };

  useEffect(() => {
    const h = (e) => {
      if (e.key === " ") { e.preventDefault(); setFlipped((f) => !f); }
      if (e.key === "1") rate("again");
      if (e.key === "2") rate("hard");
      if (e.key === "3") rate("good");
      if (e.key === "4") rate("easy");
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  if (err) return <div className="empty"><p className="banner error">{err}</p><button className="btn" onClick={onClose}>← Back</button></div>;
  if (!queue) return <div className="loading">Loading study queue…</div>;

  if (queue.cards.length === 0) {
    return (
      <div className="study done">
        <h2>🎉 Queue done</h2>
        <p className="muted">{doneCount} card{doneCount === 1 ? "" : "s"} reviewed. Review again after the due dates come up — every "Good" stretches the interval.</p>
        <div className="study-controls">
          <button className="btn" onClick={() => api.study(notebookId, recordingId, topic).then(setQueue)}>Restart (any due)</button>
          <button className="btn primary" onClick={onClose}>← Back</button>
        </div>
      </div>
    );
  }

  const card = queue.cards[idx];
  const left = queue.cards.length - 1;
  return (
    <div className="study">
      <header className="study-head">
        <button className="btn" onClick={onClose}>← Back</button>
        <h3>{title}</h3>
        <span className="muted">{queue.due_count} due · {queue.new_count} new · {left} left this session</span>
      </header>
      {card.reps > 0 && <div className="srs-meta muted">rep {card.reps} · interval {card.interval_days}d · due {card.due_date}</div>}
      <div className={"study-card" + (flipped ? " flipped" : "")} onClick={() => setFlipped((f) => !f)}>
        {flipped ? <p className="answer">{card.answer}</p> : <p className="question">{card.question}</p>}
        <span className="flip-hint">{flipped ? "answer" : "question"} — click or Space</span>
      </div>
      {flipped && (
        <div className="study-controls">
          {RATINGS.map((r) => (
            <button key={r.key} className={"btn rate " + r.cls} title={r.hint} onClick={() => rate(r.key)}>
              {r.kbd}. {r.label}
            </button>
          ))}
        </div>
      )}
      {!flipped && <p className="muted study-hint">Flip to rate the card</p>}
    </div>
  );
}