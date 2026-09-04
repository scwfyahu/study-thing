import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { askConfirm } from "../confirm.js";

const BUSY = new Set(["queued", "denoising", "splitting", "transcribing", "reading", "classifying"]);

export default function SuggestView({ notebooks, onChanged, onOpenNotebook }) {
  const [items, setItems] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newFor, setNewFor] = useState(null); // recording id being given a fresh notebook
  const [newName, setNewName] = useState("");
  const fileInput = useRef(null);

  const load = useCallback(async () => {
    try {
      const list = await api.inbox();
      setItems(list);
      onChanged && onChanged();
    } catch {}
  }, [onChanged]);

  useEffect(() => { load(); }, [load]);

  const anyBusy = items?.some((i) => BUSY.has(i.status));
  useEffect(() => {
    if (!anyBusy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [anyBusy, load]);

  const upload = async (files) => {
    setBusy(true);
    try {
      await api.bulkUpload([...files]);
    } catch (e) { alert(`Upload failed: ${e.message}`); }
    setBusy(false);
    load();
  };

  const assign = async (id, nbId) => {
    if (!nbId) return alert("Pick a notebook first.");
    try { await api.assign(id, Number(nbId)); } catch (e) { return alert(e.message); }
    onOpenNotebook(Number(nbId));
    load();
  };

  const createAndAssign = async (id, fallbackName) => {
    const name = (newName.trim() || fallbackName || "Untitled class").trim();
    try {
      const nb = await api.createNotebook(name, "");
      await assign(id, nb.id);
      setNewFor(null); setNewName("");
    } catch (e) { alert(e.message); }
  };

  const reclassify = async (id) => {
    try { await api.reclassify(id); } catch (e) { return alert(e.message); }
    load();
  };

  const del = async (id, name) => {
    if (!(await askConfirm(`Delete "${name}" and its transcript?`))) return;
    try { await api.deleteRecording(id); } catch {}
    load();
  };

  if (items === null) return <div className="loading">Loading…</div>;

  const ready = items.filter((i) => i.status === "unclassified" || i.status === "done" || i.status === "error");
  const pending = items.filter((i) => BUSY.has(i.status));

  return (
    <div className="notebook">
      <header className="nb-head">
        <div>
          <h2>Suggest notebook</h2>
          <div className="topics-line">Transcribed files waiting for a class. You approve every assignment.</div>
        </div>
        <div className="nb-actions">
          <button className="btn" onClick={load}>⟳ Refresh</button>
        </div>
      </header>

      <div className={"dropzone" + (dragging ? " over" : "") + (busy ? " busy" : "")}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); upload([...e.dataTransfer.files]); }}
        onClick={() => fileInput.current?.click()}>
        <input ref={fileInput} type="file" accept="audio/*,video/mp4,.m4a,.mp3,.wav,.webm,.mov,.png,.jpg,.jpeg,.pdf" multiple hidden
          onChange={(e) => { upload([...e.target.files]); e.target.value = ""; }} />
        {busy ? "Uploading…" : "Drop a batch here — each is transcribed, auto-classified, and held for your approval"}
      </div>

      {pending.length > 0 && (
        <section className="rec-list">
          <h4 className="muted">Processing…</h4>
          {pending.map((r) => <BusyRow key={r.id} r={r} />)}
        </section>
      )}

      <section className="rec-list">
        {ready.length === 0 && pending.length === 0 && (
          <p className="muted">Nothing waiting. Drop recordings above — they'll show up here transcribed + classified.</p>
        )}
        {ready.map((r) => (
          <EscrowRow key={r.id} r={r} notebooks={notebooks}
            onAssign={assign} onCreateStart={() => { setNewFor(r.id); setNewName(r.suggestion?.name || ""); }}
            creating={newFor === r.id} newName={newName} setNewName={setNewName}
            onCreateGo={() => createAndAssign(r.id, r.suggestion?.name || stripExt(r.original_name))}
            onCreateCancel={() => { setNewFor(null); setNewName(""); }}
            onReclassify={reclassify} onDelete={del} />
        ))}
      </section>
    </div>
  );
}

function stripExt(name) {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(0, i) : name;
}

function BusyRow({ r }) {
  const label = { queued: "Queued", denoising: "Cleaning audio", transcribing: "Transcribing", classifying: "Classifying…", reading: "Reading notes" }[r.status] || r.status;
  return (
    <div className="rec-row">
      <div className="rec-top">
        <span className="rec-name">{r.original_name}</span>
        {r.kind === "notes" && <span className="badge">Notes</span>}
        <span className={`badge s-${r.status}`}>{label}</span>
        <div className="progress"><div className="bar" style={{ width: `${Math.round((r.progress || 0) * 100)}%` }} /></div>
      </div>
    </div>
  );
}

function EscrowRow({ r, notebooks, onAssign, creating, newName, setNewName, onCreateStart, onCreateGo, onCreateCancel, onReclassify, onDelete }) {
  const [open, setOpen] = useState(false);
  const sug = r.suggestion;
  const hasSuggestion = sug && sug.name && sug.notebook_id;
  const sugExists = hasSuggestion && notebooks.some((n) => n.id === sug.notebook_id);
  const [pick, setPick] = useState(sug?.notebook_id || "");

  return (
    <div className="rec-row">
      <div className="rec-top">
        <button className="rec-toggle" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"}</button>
        <span className="rec-name">{r.original_name}</span>
        {r.kind === "notes" && <span className="badge">Notes</span>}
        <span className="badge s-unclassified">Waiting</span>
        <span className="spacer" />
        <button className="btn small" onClick={() => onReclassify(r.id)} title="Re-run classification">⟳ Re-classify</button>
        <button className="icon-del" onClick={() => onDelete(r.id, r.original_name)} title="Delete">✕</button>
      </div>

      {sug && (
        <div className={"suggestion" + (sugExists ? "" : " none")}>
          {sugExists ? (
            <>Best match: <b>{sug.name}</b> · {Math.round(sug.confidence * 100)}% sure</>
          ) : (
            <>No existing notebook matched{sug && sug.name ? <> — closest was “{sug.name}”</> : ""} (try a new one below)</>
          )}
          {sug.reason && <span className="muted"> · {sug.reason}</span>}
          {sug.topics?.length > 0 && (
            <div className="small-note muted">Covers: {sug.topics.slice(0, 6).join(" · ")}</div>
          )}
        </div>
      )}

      <div className="assign-bar">
        <select value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">Assign to…</option>
          {(notebooks || []).map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
        </select>
        <button className="btn primary" onClick={() => onAssign(r.id, pick)}>Assign</button>
        {creating ? (
          <>
            <input autoFocus className="inline-input" placeholder="New class name…" value={newName}
              onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && onCreateGo()} />
            <button className="btn primary" onClick={onCreateGo}>Create + assign</button>
            <button className="btn" onClick={onCreateCancel}>Cancel</button>
          </>
        ) : (
          <button className="btn" onClick={onCreateStart}>＋ New notebook…</button>
        )}
      </div>

      {open && (
        <div className="transcript-box">
          {r.transcript_preview
            ? <p className="muted small-note">{r.transcript_preview}{r.transcript_preview.length >= 800 ? "…" : ""}</p>
            : <p className="muted small-note">No transcript yet ({r.status}).</p>}
        </div>
      )}
      {r.status === "error" && <div className="err-text">{r.error}</div>}
    </div>
  );
}
