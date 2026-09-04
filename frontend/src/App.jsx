import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import NotebookModal from "./components/NotebookModal.jsx";
import NotebookView from "./components/NotebookView.jsx";
import ScheduleView from "./components/ScheduleView.jsx";
import SharePanel from "./components/SharePanel.jsx";
import StudyView from "./components/StudyView.jsx";
import SuggestView from "./components/SuggestView.jsx";
import { askConfirm } from "./confirm.js";

export default function App() {
  const [notebooks, setNotebooks] = useState([]);
  const [proc, setProc] = useState(null);
  const [inboxN, setInboxN] = useState(0);
  useEffect(() => {
    const check = async () => {
      try { setProc(await fetch("/api/processing").then((r) => r.json())); } catch {}
      try { setInboxN((await fetch("/api/inbox/count").then((r) => r.json())).count || 0); } catch {}
    };
    check();
    const t = setInterval(check, 5000);
    return () => clearInterval(t);
  }, []);
  const [currentId, setCurrentId] = useState(null);
  const [viewSchedule, setViewSchedule] = useState(false);
  const [viewSuggest, setViewSuggest] = useState(false);
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
    if (!(await askConfirm(`Delete notebook "${nb.name}" and all its recordings + flashcards?`))) return;
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
            className={"nb-item" + (viewSuggest ? " active" : "")}
            onClick={() => { setViewSuggest(true); setViewSchedule(false); setCurrentId(null); setStudy(null); }}
          >
            <div className="nb-name">Suggest notebook {inboxN > 0 && <span className="badge-count">{inboxN}</span>}</div>
            <div className="nb-meta">unfiled transcripts</div>
          </div>
          <div
            className={"nb-item" + (viewSchedule ? " active" : "")}
            onClick={() => { setViewSchedule(true); setViewSuggest(false); setStudy(null); }}
          >
            <div className="nb-name">Quiz schedule</div>
            <div className="nb-meta">all subjects</div>
          </div>
          {notebooks.map((nb) => (
            <div
              key={nb.id}
              className={"nb-item" + (nb.id === currentId && !viewSchedule && !viewSuggest ? " active" : "")}
              onClick={() => { setCurrentId(nb.id); setViewSchedule(false); setViewSuggest(false); setStudy(null); }}
            >
              <div className="nb-name">{nb.name}</div>
              <div className="nb-meta">{nb.recording_count} rec · {nb.card_count} cards</div>
              <button className="nb-del" title="Rename" onClick={(e) => renameNotebook(nb, e)}>Rename</button>
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
        <SharePanel />
        <div className="sidebar-foot">100% local · nothing leaves this Mac</div>
      </aside>

      <main className="main">
        {proc?.busy && (
          <div className="proc-bar">
            <span className="proc-dot" /> Processing…
            {proc.recordings > 0 && ` ${proc.recordings} recording${proc.recordings > 1 ? "s" : ""}`}
            {proc.decks > 0 && ` · ${proc.decks} deck${proc.decks > 1 ? "s" : ""}`}
            {proc.tests_waiting > 0 && ` · ${proc.tests_waiting} test${proc.tests_waiting > 1 ? "s" : ""} awaiting scope`}
          </div>
        )}
        {error && <div className="banner error">{error}</div>}
        {study ? (
          <StudyView
            notebookId={study.notebookId}
            recordingId={study.recordingId}
            topic={study.topic}
            title={study.title}
            onClose={() => setStudy(null)}
          />
        ) : viewSuggest ? (
          <SuggestView
            notebooks={notebooks}
            onChanged={refresh}
            onOpenNotebook={(id) => { setCurrentId(id); setViewSuggest(false); }}
          />
        ) : viewSchedule ? (
          <ScheduleView onOpenNotebook={(id) => { setCurrentId(id); setViewSchedule(false); }} />
        ) : currentId ? (
          <NotebookView
            key={currentId}
            notebookId={currentId}
            notebooks={notebooks}
            onStudy={(title, recordingId, topic) => setStudy({ title, notebookId: currentId, recordingId, topic })}
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