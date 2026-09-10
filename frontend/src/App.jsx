import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import NotebookModal from "./components/NotebookModal.jsx";
import NotebookView from "./components/NotebookView.jsx";
import ScheduleView from "./components/ScheduleView.jsx";
import SharePanel from "./components/SharePanel.jsx";
import StudyView from "./components/StudyView.jsx";
import SuggestView from "./components/SuggestView.jsx";
import HomeView from "./components/HomeView.jsx";
import SetupView from "./components/SetupView.jsx";
import { askConfirm } from "./confirm.js";

const fmtHm = (min) => {
  if (!min || min < 1) return "0m";
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  return (h ? `${h}h ` : "") + (m || !h ? `${m}m` : "");
};

export default function App() {
  const [notebooks, setNotebooks] = useState([]);
  const [proc, setProc] = useState(null);
  const [inboxN, setInboxN] = useState(0);
  const [update, setUpdate] = useState(null);
  const [upgrading, setUpgrading] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem("st-theme");
    if (saved) return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("st-theme", theme);
  }, [theme]);
  useEffect(() => {
    const check = async () => {
      try { setProc(await fetch("/api/processing").then((r) => r.json())); } catch {}
      try { setInboxN((await fetch("/api/inbox/count").then((r) => r.json())).count || 0); } catch {}
      try { setUpdate(await fetch("/api/update").then((r) => r.json())); } catch {}
      try { setNeedsSetup((await fetch("/api/setup/status").then((r) => r.json())).needed); } catch {}
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
        <h1 className="brand" style={{cursor:"pointer"}} title="Home"
            onClick={() => { setViewSuggest(false); setViewSchedule(false); setCurrentId(null); setStudy(null); }}>Study<span>Thing</span></h1>
        <nav className="nb-list">
          <div className="side-h">Inbox</div>
          <div
            className={"nb-item" + (viewSuggest ? " active" : "")}
            onClick={() => { setViewSuggest(true); setViewSchedule(false); setCurrentId(null); setStudy(null); }}
          >
            <div className="nb-name" title="Suggest notebook">Suggest notebook {inboxN > 0 && <span className="badge-count">{inboxN}</span>}</div>
            <div className="nb-meta">unfiled transcripts</div>
          </div>
          <div
            className={"nb-item" + (viewSchedule ? " active" : "")}
            onClick={() => { setViewSchedule(true); setViewSuggest(false); setStudy(null); }}
          >
            <div className="nb-name" title="Quiz schedule">Quiz schedule</div>
            <div className="nb-meta">all subjects</div>
          </div>
          <div className="side-split" />
          <div className="side-h">Notebooks</div>
          {notebooks.map((nb) => (
            <div
              key={nb.id}
              className={"nb-item" + (nb.id === currentId && !viewSchedule && !viewSuggest ? " active" : "")}
              onClick={() => { setCurrentId(nb.id); setViewSchedule(false); setViewSuggest(false); setStudy(null); }}
            >
              <div className="nb-name" title={nb.name}>{nb.name}</div>
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
        <div className="sidebar-foot-row">
          {update?.available && (
            <button className="theme-toggle update-btn"
              disabled={upgrading}
              onClick={async () => {
                if (!(await askConfirm(
                  `Install update ${update.latest}?\nYour recordings and settings are kept. The app restarts automatically.`
                ))) return;
                setUpgrading(true);
                try { await fetch("/api/update/install", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: update.url }) }); } catch {}
              }}>
              {upgrading ? "Downloading update…" : `⟳ Update ${update.latest}`}
            </button>
          )}
          <button className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
        </div>
        <div className="sidebar-foot">100% local · nothing leaves this Mac</div>
      </aside>

      <main className="main">
        {needsSetup ? (
          <SetupView onDone={() => setNeedsSetup(false)} />
        ) : (
        <>
        {proc?.busy && (
          <div className="proc-bar">
            <span className="proc-dot" /> Processing…
            {proc.recordings > 0 && ` ${proc.recordings} recording${proc.recordings > 1 ? "s" : ""}`}
            {proc.total_min > 0 && ` · ${fmtHm(proc.done_min)} of ${fmtHm(proc.total_min)} audio`}
            {proc.decks > 0 && ` · ${proc.decks} deck${proc.decks > 1 ? "s" : ""}`}
            {proc.tests_waiting > 0 && ` · ${proc.tests_waiting} test${proc.tests_waiting > 1 ? "s" : ""} awaiting scope`}
            <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--color-muted)" }}>{Math.round((proc.progress || 0) * 100)}%</span>
            <button
              className="btn small"
              style={{ marginLeft: "auto" }}
              onClick={async () => {
                const ok = await askConfirm("Stop all jobs? Queued recordings stay as files but won't be processed until you re-process them.");
                if (!ok) return;
                try {
                  await fetch("/api/jobs/stop", { method: "POST" });
                } catch {}
                try { setProc(await fetch("/api/processing").then((r) => r.json())); } catch {}
              }}
            >Stop all</button>
          </div>
        )}
      {proc?.busy && (
        <div className="progress proc-progress">
          <div className="bar" style={{ width: `${Math.round((proc.progress || 0) * 100)}%` }} />
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
          <HomeView
            onOpenNotebook={(id) => { setCurrentId(id); setViewSuggest(false); setViewSchedule(false); }}
            onOpenSuggest={() => { setViewSuggest(true); setViewSchedule(false); setCurrentId(null); }}
            onOpenSchedule={() => { setViewSchedule(true); setViewSuggest(false); setCurrentId(null); }}
            onNewNotebook={() => setModal({ mode: "create" })}
          />
        )}
        {modal && (
          <NotebookModal
            initial={modal.mode === "edit" ? modal.nb : null}
            onSave={saveNotebook}
            onClose={() => setModal(null)}
          />
        )}
        </>
        )}
      </main>
    </div>
  );
}