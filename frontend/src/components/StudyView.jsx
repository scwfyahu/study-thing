import React, { useEffect, useState } from "react";

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export default function StudyView({ title, cards, onClose }) {
  const [order, setOrder] = useState(() => shuffle(cards));
  const [idx, setIdx] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [known, setKnown] = useState(() => new Set());

  const card = order[idx];

  const next = () => { setFlipped(false); setIdx((i) => Math.min(i + 1, order.length - 1)); };
  const prev = () => { setFlipped(false); setIdx((i) => Math.max(i - 1, 0)); };
  const mark = (isKnown) => {
    const s = new Set(known);
    isKnown ? s.add(card.q) : s.delete(card.q);
    setKnown(s);
    if (idx < order.length - 1) next();
  };

  useEffect(() => {
    const h = (e) => {
      if (e.key === " ") { e.preventDefault(); setFlipped((f) => !f); }
      if (e.key === "ArrowRight") next();
      if (e.key === "ArrowLeft") { setFlipped(false); setIdx((i) => Math.max(i - 1, 0)); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [order.length, idx]);

  if (!card) return <div className="empty"><p>No cards.</p></div>;

  return (
    <div className="study">
      <header className="study-head">
        <button className="btn" onClick={onClose}>← Back</button>
        <h3>{title}</h3>
        <span className="muted">{idx + 1} / {order.length} · known {known.size}</span>
      </header>
      <div
        className={"study-card" + (flipped ? " flipped" : "")}
        onClick={() => setFlipped((f) => !f)}
        title="Click or press Space to flip"
      >
        {flipped ? <p className="answer">{card.a}</p> : <p className="question">{card.q}</p>}
        <span className="flip-hint">{flipped ? "question" : "answer"}</span>
      </div>
      <div className="study-controls">
        <button className="btn" onClick={() => mark(false)}>✗ Not yet</button>
        <button className="btn" onClick={() => { setFlipped(false); setOrder(shuffle(cards)); setIdx(0); }}>⇄ Shuffle</button>
        <button className="btn good" onClick={() => mark(true)}>✓ Got it</button>
      </div>
      <div className="study-nav">
        <button className="btn" disabled={idx === 0} onClick={() => { setFlipped(false); setIdx((i) => Math.max(i - 1, 0)); }}>← Prev</button>
        <button className="btn" disabled={idx === order.length - 1} onClick={next}>Next →</button>
      </div>
    </div>
  );
}