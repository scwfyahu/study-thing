import React, { useState } from "react";

export default function QuizModal({ tests, topicOptions, onSave, onClose }) {
  const [source, setSource] = useState("__all__");
  const [difficulty, setDifficulty] = useState(5);
  const [num, setNum] = useState(10);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    try {
      await onSave(source, difficulty, num);
      onClose();
    } catch (ex) {
      setErr(ex.message);
    }
  };

  const scopeOf = (src) => {
    if (src === "__all__") return [];
    if (src.startsWith("topic:")) return [src.slice(6)];
    const t = tests.find((x) => `test:${x.id}` === src);
    return t?.scope || [];
  };
  const labelOf = (src) => {
    if (src === "__all__") return "All cards";
    if (src.startsWith("topic:")) return src.slice(6);
    return tests.find((x) => `test:${x.id}` === src)?.title || src;
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>New quiz</h3>
        <label>Scope (from test schedule / syllabus)</label>
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="__all__">All cards in notebook</option>
          {tests.map((t) => (
            <option key={t.id} value={`test:${t.id}`}>{t.title} {t.date_iso ? `(${t.date_iso})` : ""}</option>
          ))}
          {topicOptions.map((t) => (
            <option key={t} value={`topic:${t}`}>{t}</option>
          ))}
        </select>
        <label>Difficulty: <b>{difficulty}/10</b></label>
        <input type="range" min="1" max="10" value={difficulty}
               onChange={(e) => setDifficulty(Number(e.target.value))} />
        <div className="muted small-note">1-3 recall · 4-7 application · 8-10 analysis + tricky distractors</div>
        <label>Questions</label>
        <input type="number" min="1" max="25" value={num} onChange={(e) => setNum(Number(e.target.value))} />
        {err && <div className="banner error">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary">Generate quiz</button>
        </div>
      </form>
    </div>
  );
}