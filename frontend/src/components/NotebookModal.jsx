import React, { useState } from "react";

export default function NotebookModal({ initial, onSave, onClose }) {
  const [name, setName] = useState(initial?.name || "");
  const [topics, setTopics] = useState(initial?.topics || "");
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await onSave(name.trim(), topics.trim());
      onClose();
    } catch (ex) {
      setErr(ex.message);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>{initial ? "Edit notebook" : "New class notebook"}</h3>
        <label>Name</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Biology, Life and Career Skills…"
        />
        <label>Focus topics <span className="muted">(optional — one per line)</span></label>
        <textarea
          rows={5}
          value={topics}
          onChange={(e) => setTopics(e.target.value)}
          placeholder={"Flashcards only cover these syllabus topics.\nPaste from the syllabus, one topic per line.\nLeave empty to allow all content."}
        />
        {err && <div className="banner error">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!name.trim()}>
            {initial ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}