import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const STATUS_LABEL = {
  queued: "Queued",
  denoising: "Cleaning audio",
  splitting: "Splitting",
  transcribing: "Transcribing",
  extracting: "Making flashcards",
  done: "Done",
  error: "Failed",
};
const ACTIVE = new Set(["queued", "denoising", "splitting", "transcribing", "extracting"]);

function fmtDur(s) {
  if (!s) return "";
  const m = Math.floor(s / 60);
  return `${Math.floor(m / 60) ? `${Math.floor(m / 60)}h ` : ""}${m % 60}m`;
}

export default function NotebookView({ notebookId, notebooks, onStudy, onEditFocus }) {
  const [nb, setNb] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef(null);

  const load = useCallback(async () => {
    try {
      setNb(await api.notebook(notebookId));
    } catch {
      /* transient */
    }
  }, [notebookId]);

  useEffect(() => {
    load();
  }, [load]);

  const hasActive = nb?.recordings?.some((r) => ACTIVE.has(r.status));
  useEffect(() => {
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load, hasActive]);

  const uploadFiles = async (files) => {
    setBusy(true);
    for (const f of files) {
      try {
        await api.upload(notebookId, f);
      } catch (e) {
        alert(`${f.name}: ${e.message}`);
      }
    }
    setBusy(false);
    load();
  };

  const startStudy = async () => {
    const cards = await api.cards(notebookId);
    if (!cards.length) return alert("No flashcards yet — wait for a recording to finish.");
    onStudy(nb.name, cards.map((c) => ({ q: c.question, a: c.answer })));
  };

  const editTopics = () => {
    onEditFocus(nb);
  };

  if (!nb) return <div className="loading">Loading…</div>;

  return (
    <div className="notebook">
      <header className="nb-head">
        <div>
          <h2>{nb.name}</h2>
          {nb.topics && <div className="topics-line">Focus: {nb.topics}</div>}
        </div>
        <div className="nb-actions">
          <button className="btn" onClick={() => editTopics()}>Focus</button>
          <button className="primary" onClick={startStudy}>▶ Study all</button>
          <a className="btn" href={`/api/notebooks/${nb.id}/export?format=apkg`}>Export Anki</a>
          <a className="btn" href={`/api/notebooks/${nb.id}/export?format=csv`}>Export CSV</a>
        </div>
      </header>

      <div
        className={"dropzone" + (dragging ? " over" : "") + (busy ? " busy" : "")}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); uploadFiles([...e.dataTransfer.files]); }}
        onClick={() => fileInput.current?.click()}
      >
        <input
          ref={fileInput}
          type="file"
          accept="audio/*,video/mp4,.m4a,.mp3,.wav,.webm,.mov"
          multiple
          hidden
          onChange={(e) => { uploadFiles([...e.target.files]); e.target.value = ""; }}
        />
        {busy ? "Uploading…" : "Drop lecture recordings here, or click to browse"}
      </div>

      <section className="rec-list">
        {nb.recordings.length === 0 && <p className="muted">No recordings yet.</p>}
        {nb.recordings.map((r) => (
          <RecordingRow key={r.id} r={r} onChanged={load} onStudy={onStudy} nbName={nb.name} notebooks={notebooks} />
        ))}
      </section>
    </div>
  );
}

function RecordingRow({ r, onChanged, onStudy, nbName, notebooks }) {
  const [open, setOpen] = useState(false);
  const [cards, setCards] = useState(null);
  const active = ACTIVE.has(r.status);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && r.status === "done") {
      const rows = await fetch(`/api/recordings/${r.id}/cards`).then((x) => x.json());
      setCards(rows);
    }
  };

  const studyThis = async () => {
    const rows = await fetch(`/api/recordings/${r.id}/cards`).then((x) => x.json());
    if (!rows.length) return alert("No flashcards in this recording yet.");
    onStudy(r.original_name, rows.map((c) => ({ q: c.question, a: c.answer })));
  };

  const del = async () => {
    if (!confirm(`Delete "${r.original_name}" and its flashcards?`)) return;
    await api.deleteRecording(r.id);
    onChanged();
  };

  const move = async (notebookId) => {
    if (!notebookId || Number(notebookId) === r.notebook_id) return;
    await api.moveRecording(r.id, Number(notebookId));
    onChanged();
  };

  const reprocess = async () => {
    if (!confirm("Re-run transcription + flashcard generation for this recording? (existing cards are rebuilt)")) return;
    await api.reprocess(r.id);
    onChanged();
  };

  return (
    <div className="rec-row">
      <div className="rec-top">
        <button className="rec-toggle" onClick={toggle}>{open ? "▾" : "▸"}</button>
        <span className="rec-name">{r.original_name}</span>
        <span className={`badge s-${r.status}`}>{STATUS_LABEL[r.status] || r.status}</span>
        {r.duration_sec ? <span className="muted">{fmtDur(r.duration_sec)}</span> : null}
        <span className="spacer" />
        {r.status === "done" && (
          <>
            <button className="btn small" onClick={studyThis}>▶ Study</button>
            <button className="btn small" onClick={reprocess}>↻ Re-process</button>
            <a className="btn small" href={`/api/recordings/${r.id}/export?format=apkg`}>Anki</a>
            <a className="btn small" href={`/api/recordings/${r.id}/export?format=csv`}>CSV</a>
          </>
        )}
        <select
          className="move-select"
          value={r.notebook_id}
          onChange={(e) => move(e.target.value)}
          title="Assign to class notebook"
        >
          {(notebooks || []).map((n) => (
            <option key={n.id} value={n.id}>{n.name}</option>
          ))}
        </select>
        <button className="icon-del" onClick={del} title="Delete recording">✕</button>
      </div>
      {active && (
        <div className="progress"><div className="bar" style={{ width: `${Math.round(r.progress * 100)}%` }} /></div>
      )}
      {r.status === "error" && <div className="err-text">{r.error}</div>}
      {r.note && r.status === "done" && <div className="muted small-note">{r.note}</div>}
      {open && cards !== null && (
        <div className="cards">
          {cards.length === 0 && <p className="muted">No cards.</p>}
          {cards.map((c) => (
            <details key={c.id} className="card">
              <summary>{c.question}</summary>
              <p>{c.answer}</p>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}