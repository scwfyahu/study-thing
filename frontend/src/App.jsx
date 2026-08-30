import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import NotebookModal from "./components/NotebookModal.jsx";
import NotebookView from "./components/NotebookView.jsx";
import ScheduleView from "./components/ScheduleView.jsx";
import StudyView from "./components/StudyView.jsx";

export default function App() {
  const [notebooks, setNotebooks] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [viewSchedule, setViewSchedule] = useState(false);
  const [modal, setModal] = useState(null); // {mode:'create'} | {mode:'edit', nb}
  const [study, setStudy] = useState(null); // {title, notebookId}
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

  const saveNotebook = async (name, topics, syllabus) => {
    if (modal?.mode === "create") return createNotebook(name, topics, syllabus);
    const nb = modal.nb;
    const body = {};
    if (name !== nb.name) body.name = name;
    if (topics !== (nb.topics || "")) body.topics = topics;
    if (syllabus) body.syllabus = syllabus;
    if (Object.keys(body).length) await api.updateNotebook(nb.id, body);
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
          <div
            className={"nb-item" + (viewSchedule ? " active" : "")}
            onClick={() => { setViewSchedule(true); setStudy(null); }}
          >
            <div className="nb-name">📅 Quiz schedule</div>
            <div className="nb-meta">all subjects</div>
          </div>
          {notebooks.map((nb) => (
            <div
              key={nb.id}
              className={"nb-item" + (nb.id === currentId && !viewSchedule ? " active" : "")}
              onClick={() => { setCurrentId(nb.id); setViewSchedule(false); setStudy(null); }}
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
          <StudyView
            notebookId={study.notebookId}
            recordingId={study.recordingId}
            title={study.title}
            onClose={() => setStudy(null)}
          />
        ) : viewSchedule ? (
          <ScheduleView onOpenNotebook={(id) => { setCurrentId(id); setViewSchedule(false); }} />
        ) : currentId ? (
          <NotebookView
            key={currentId}
            notebookId={currentId}
            notebooks={notebooks}
            onStudy={(title, recordingId) => setStudy({ title, notebookId: currentId, recordingId })}
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