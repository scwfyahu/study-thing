import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import NotebookView from "./components/NotebookView.jsx";
import StudyView from "./components/StudyView.jsx";

export default function App() {
  const [notebooks, setNotebooks] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [newName, setNewName] = useState("");
  const [study, setStudy] = useState(null); // {title, cards}
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setNotebooks(await api.notebooks());
      setError("");
    } catch (e) {
      setError(`Backend unreachable — is it running on :8765? (${e.message})`);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, [refresh]);

  const current = notebooks.find((n) => n.id === currentId) || null;

  const createNotebook = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const nb = await api.createNotebook(newName.trim());
      setNewName("");
      await refresh();
      setCurrentId(nb.id);
    } catch (err) {
      setError(err.message);
    }
  };

  const deleteNotebook = async (nb, e) => {
    e.stopPropagation();
    if (!confirm(`Delete notebook "${nb.name}" and all its recordings + flashcards?`)) return;
    await api.deleteNotebook(nb.id);
    if (currentId === nb.id) setCurrentId(null);
    refresh();
  };

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1 className="brand">Study<span>Thing</span></h1>
        <nav className="nb-list">
          {notebooks.map((nb) => (
            <div
              key={nb.id}
              className={"nb-item" + (nb.id === currentId ? " active" : "")}
              onClick={() => { setCurrentId(nb.id); setStudy(null); }}
            >
              <div className="nb-name">{nb.name}</div>
              <div className="nb-meta">{nb.recording_count} rec · {nb.card_count} cards</div>
              <button className="nb-del" title="Delete notebook" onClick={(e) => deleteNotebook(nb, e)}>×</button>
            </div>
          ))}
        </nav>
        <form className="new-nb" onSubmit={createNotebook}>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New class notebook…"
          />
          <button type="submit" disabled={!newName.trim()}>＋</button>
        </form>
        <div className="sidebar-foot">100% local · nothing leaves this Mac</div>
      </aside>

      <main className="main">
        {error && <div className="banner error">{error}</div>}
        {study ? (
          <StudyView title={study.title} cards={study.cards} onClose={() => setStudy(null)} />
        ) : currentId ? (
          <NotebookView
            key={currentId}
            notebookId={currentId}
            onStudy={(title, cards) => setStudy({ title, cards })}
          />
        ) : (
          <div className="empty">
            <h2>Your classes, distilled to flashcards.</h2>
            <p>Create a notebook for each class, then drop in your lecture recordings.</p>
            <p className="hint">Noise gets cleaned (ffmpeg) → transcribed locally (MLX Whisper) → turned into flashcards (Ollama).</p>
          </div>
        )}
      </main>
    </div>
  );
}