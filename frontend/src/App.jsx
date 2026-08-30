import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import NotebookModal from "./components/NotebookModal.jsx";
import NotebookView from "./components/NotebookView.jsx";
import StudyView from "./components/StudyView.jsx";

export default function App() {
  const [notebooks, setNotebooks] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [modal, setModal] = useState(null); // {mode:'create'} | {mode:'edit', nb}
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

  const createNotebook = async (name, topics) => {
    const nb = await api.createNotebook(name, topics);
    await refresh();
    setCurrentId(nb.id);
  };

  const saveNotebook = async (name, topics) => {
    if (modal?.mode === "create") return createNotebook(name, topics);
    const nb = modal.nb;
    if (name !== nb.name) await api.renameNotebook(nb.id, name);
    if (topics !== (nb.topics || "")) await api.setTopics(nb.id, topics);
    await refresh();
  };

  const deleteNotebook = async (nb, e) => {
    e.stopPropagation();
    if (!confirm(`Delete notebook "${nb.name}" and all its recordings + flashcards?`)) return;
    await api.deleteNotebook(nb.id);
    if (currentId === nb.id) setCurrentId(null);
    refresh();
  };

  const renameNotebook = async (nb, e) => {
    e.stopPropagation();
    setModal({ mode: "edit", nb });
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
              <button className="nb-del" title="Rename" onClick={(e) => renameNotebook(nb, e)}>✎</button>
              <button className="nb-del nb-del-del" title="Delete notebook" onClick={(e) => deleteNotebook(nb, e)}>×</button>
            </div>
          ))}
        </nav>
        <form className="new-nb" onSubmit={(e) => { e.preventDefault(); setModal({ mode: "create" }); }}>
          <input
            value=""
            placeholder="New class notebook…"
            onFocus={() => setModal({ mode: "create" })}
            readOnly
          />
          <button type="submit">＋</button>
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
            notebooks={notebooks}
            onStudy={(title, cards) => setStudy({ title, cards })}
            onEditFocus={(nb) => setModal({ mode: "edit", nb })}
          />
        ) : (
          <div className="empty">
            <h2>Your classes, distilled to flashcards.</h2>
            <p>Create a notebook for each class, then drop in your lecture recordings.</p>
            <p className="hint">Noise gets cleaned (ffmpeg) → transcribed locally (MLX Whisper) → turned into flashcards (Ollama).</p>
          </div>
        )}
        {modal && (
          <NotebookModal
            initial={modal.mode === "edit" ? modal.nb : null}
            onSave={saveNotebook}
            onClose={() => setModal(null)}
          />
        )}
      </main>
    </div>
  );
}