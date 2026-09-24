import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Outline from "./Outline.jsx";
import FocusView from "./FocusView.jsx";
import TranscriptModal from "./TranscriptModal.jsx";
import SplitModal from "./SplitModal.jsx";
import useAudioReady from "./useAudioReady.js";
import { askConfirm } from "../confirm.js";

export const STATUS_LABEL = {
  queued: "Queued",
  denoising: "Cleaning audio",
  splitting: "Splitting",
  transcribing: "Transcribing",
  reading: "Reading notes",
  done: "Done",
  error: "Failed",
};
const ACTIVE = new Set(["queued", "denoising", "splitting", "transcribing"]);

function fmtDur(s) {
  if (!s) return "";
  const m = Math.floor(s / 60);
  return `${Math.floor(m / 60) ? `${Math.floor(m / 60)}h ` : ""}${m % 60}m`;
}

export default function NotebookView({ notebookId, notebooks, onOpenReviewer, onEditFocus }) {
  const [nb, setNb] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [splitRec, setSplitRec] = useState(null); // recording proposed for auto-split
  const [busy, setBusy] = useState(false);
  const [reviewers, setReviewers] = useState([]);
  const [openRev, setOpenRev] = useState(null); // reviewer id expanded
  const [revContent, setRevContent] = useState(null);
  const [tests, setTests] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [autoFocusing, setAutoFocusing] = useState(false);
  const [srcTab, setSrcTab] = useState("recordings");
  const [selTopic, setSelTopic] = useState(null);
  const [focus, setFocus] = useState([]);
  const [generatingFocus, setGeneratingFocus] = useState(false);
  const [transcriptModal, setTranscriptModal] = useState(null); // {title, data}
  const fileInput = useRef(null);

  const openNbTranscript = async () => {
    try { setTranscriptModal({ title: `Transcripts — ${nb.name}`, data: await api.notebookTranscript(notebookId) }); }
    catch (e) { alert(e.message); }
  };
  const openRecTranscript = async (r) => {
    try {
      const t = await api.transcript(r.id);
      setTranscriptModal({ title: `${r.kind === "notes" ? "Outline" : "Transcript"} — ${r.original_name}`, data: { recordings: [{ id: r.id, name: r.original_name, duration_sec: r.duration_sec, chunks: t.chunks }] } });
    } catch (e) { alert(e.message); }
  };

  const load = useCallback(async () => {
    try {
      const [n, rvs, ts, fc] = await Promise.all([
        api.notebook(notebookId), api.reviewers(), api.tests(notebookId), api.focus(notebookId),
      ]);
      setNb(n);
      setReviewers(rvs.filter((x) => x.notebook_id === notebookId));
      setTests(ts);
      setFocus(fc.focus || []);
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

  const editTopics = () => {
    onEditFocus(nb);
  };

  const autoFocus = async () => {
    setAutoFocusing(true);
    setGeneratingFocus(true);
    try {
      await api.autoFocus(notebookId);
      // generation runs in background; poll to pick it up
      let tries = 0;
      const poll = async () => {
        const fc = await api.focus(notebookId).catch(() => null);
        if (fc) setFocus(fc.focus || []);
        if (!fc?.focus?.length && tries++ < 12) setTimeout(poll, 3000);
        else setGeneratingFocus(false);
      };
      poll();
      await load();
    } catch (ex) {
      alert(ex.message);
      setGeneratingFocus(false);
    }
    setAutoFocusing(false);
  };

  const toggleRev = async (id) => {
    if (openRev === id) {
      setOpenRev(null);
      setRevContent(null);
      return;
    }
    setOpenRev(id);
    const r = await fetch(`/api/reviewers/${id}`).then((x) => x.json());
    setRevContent(r.content);
  };

  const delRev = async (id) => {
    if (!(await askConfirm("Delete this reviewer?"))) return;
    await api.deleteReviewer(id);
    setOpenRev(null);
    load();
  };

  const scanForTests = async () => {
    setScanning(true);
    await api.scanTests(notebookId);
    setScanning(false);
    load();
  };

  const fmtDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    const days = Math.ceil((d - new Date()) / 86400000);
    return d.toDateString().slice(0, 10) + (days < 0 ? ` (${-days}d ago)` : days === 0 ? " (today)" : ` (in ${days}d)`);
  };

  const deleteTest = async (id) => {
    await api.deleteTest(id);
    load();
  };

  const recRows = (nb?.recordings || []).filter((r) => r.kind !== "notes");
  const noteRows = (nb?.recordings || []).filter((r) => r.kind === "notes");
  useEffect(() => {
    if (srcTab === "recordings" && !recRows.length && noteRows.length) setSrcTab("notes");
  }, [nb]);

  if (!nb) return <div className="loading">Loading…</div>;

  const srcRows = srcTab === "notes" ? noteRows : recRows;

  return (
    <div className="notebook">
      <header className="nb-head">
        <div>
          <h2>{nb.name}</h2>
          {nb.topics && <div className="topics-line">Focus: {nb.topics}</div>}
        </div>
        <div className="nb-actions">
          <button className="btn" onClick={openNbTranscript}>Transcripts</button>
          {nb.has_syllabus && (
            <button className="btn" onClick={autoFocus} disabled={autoFocusing}>
              {autoFocusing ? "Extracting…" : "⟳ Auto-focus"}
            </button>
          )}
          <button className="btn" onClick={() => editTopics()} title="Edit the focus topic list and syllabus">✎ Edit focus</button>
          <button className="primary" onClick={() => onOpenReviewer && onOpenReviewer(nb.id)}>
            ▶ Make reviewer
          </button>
        </div>
      </header>

      <section className="focus-section">
        <FocusView focus={focus} generating={generatingFocus} onRegenerate={autoFocus} hasSyllabus={nb.has_syllabus} />
      </section>

      <section className="tests-section">
        <div className="rev-bar">
          <h4>Upcoming tests</h4>
          <button className="btn small" onClick={scanForTests} disabled={scanning}>
            {scanning ? "Scanning transcripts…" : "⟳ Scan for test announcements"}
          </button>
        </div>
        {tests.length === 0 && <p className="muted small-note">No tests found yet — recordings get scanned automatically after processing, or scan manually.</p>}
        {tests.map((t) => (
          <div key={t.id} className={"test-card" + (t.date_iso ? " dated" : "")}>
            <div className="test-head">
              <span className="test-title">{t.title}</span>
              {t.date_text && <span className="test-date">{t.date_text}</span>}
              {fmtDate(t.date_iso) && <span className="test-iso">{fmtDate(t.date_iso)}</span>}
              <span className="spacer" />
              <span className="muted small-note">{t.recording_name || ""}</span>
              <button className="icon-del" onClick={() => deleteTest(t.id)} title="Delete">✕</button>
            </div>
            {t.scope?.length > 0 && (
              <ul className="test-scope">
                {t.scope.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            )}
          </div>
        ))}
      </section>

      <section className="rev-section recordings-panel">
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
          accept="audio/*,video/*,.m4a,.mp3,.wav,.webm,.mov,.flac,.opus,.aac,.m4b,.wma,.aif,.aiff,image/*,.pdf,.txt,.md,.csv,.docx"
          multiple
          hidden
          onChange={(e) => { uploadFiles([...e.target.files]); e.target.value = ""; }}
        />
        {busy ? "Uploading…" : "Drop lecture recordings or handwritten note photos/PDFs here"}
      </div>

      <div className="src-tabs">
        <button className={"src-tab" + (srcTab === "recordings" ? " active" : "")} onClick={() => setSrcTab("recordings")}>
          Recordings ({recRows.length})
        </button>
        <button className={"src-tab" + (srcTab === "notes" ? " active" : "")} onClick={() => setSrcTab("notes")}>
          Notes ({noteRows.length})
        </button>
      </div>

      <section className="rec-list">
        {srcRows.length === 0 && (
          <p className="muted">
            {srcTab === "notes"
              ? "No notes yet — drop photos or PDFs of handwritten notes above."
              : "No recordings yet — drop lecture audio above."}
          </p>
        )}
        {srcRows.map((r) => (
          <RecordingRow key={r.id} r={r} onChanged={load} nbName={nb.name} nbId={nb.id} notebooks={notebooks} onTranscript={openRecTranscript} onSplit={(rec) => setSplitRec(rec)} />
        ))}
      </section>
      </section>

      <section className="rev-section">
        <div className="rev-bar">
          <h4>Reviewers</h4>
          <button className="btn primary" onClick={() => onOpenReviewer && onOpenReviewer(nb.id)}>＋ New reviewer</button>
        </div>
        {reviewers.length === 0 && <p className="muted small-note">No reviewers yet — pick recordings by date/topic in the Reviewer tab and generate a study guide from their transcripts.</p>}
        {reviewers.map((rv) => (
          <div key={rv.id} className="rev-row">
            <button className="rev-main" onClick={() => toggleRev(rv.id)}>
              <span className="rev-topic">{rv.topic}</span>
              <span className={`badge s-${rv.status === "ready" ? "done" : rv.status === "error" ? "error" : rv.status}`}>{rv.status}</span>
              <span className="muted">{rv.created_at.slice(0, 16).replace("T", " ")}{rv.chars ? ` · ${Math.round(rv.chars / 100) / 10}k chars` : ""}</span>
            </button>
            <a className="btn small" href={`/api/reviewers/${rv.id}/download?format=md`}>.md</a>
            <a className="btn small" href={`/api/reviewers/${rv.id}/download?format=txt`}>.txt</a>
            <button className="icon-del" onClick={() => delRev(rv.id)} title="Delete reviewer">✕</button>
            {openRev === rv.id && rv.status === "error" && (
              <div className="rev-body"><p className="err-text">{rv.error || "generation failed"}</p></div>
            )}
            {openRev === rv.id && rv.status !== "error" && (
              <div className="rev-body">
                {revContent ? <Outline content={revContent} /> : <p className="muted">Loading…</p>}
              </div>
            )}
          </div>
        ))}
      </section>

      {transcriptModal && <TranscriptModal title={transcriptModal.title} data={transcriptModal.data} onClose={() => setTranscriptModal(null)} />}
      {splitRec && (
        <SplitModal rec={splitRec} notebooks={notebooks}
          onClose={() => setSplitRec(null)}
          onDone={() => { setSplitRec(null); load(); }} />
      )}
    </div>
  );
}

function RecordingRow({ r, onChanged, nbName, nbId, notebooks, onTranscript, onSplit }) {
  const active = ACTIVE.has(r.status);
  const [listen, setListen] = useState(false);

  const del = async () => {
    if (!(await askConfirm(`Delete "${r.original_name}" and its transcript?`))) return;
    await api.deleteRecording(r.id);
    onChanged();
  };

  const move = async (notebookId) => {
    if (!notebookId || Number(notebookId) === r.notebook_id) return;
    await api.moveRecording(r.id, Number(notebookId));
    onChanged();
  };

  const reprocess = async () => {
    if (!(await askConfirm("Re-run transcription for this recording? (chunks are rebuilt)"))) return;
    await api.reprocess(r.id);
    onChanged();
  };

  const audioState = useAudioReady(r.id, listen);

  return (
    <div className="rec-row">
      <div className="rec-top">
        <span className="rec-name">{r.original_name}</span>
        {r.kind === "notes" && <span className="badge">Notes</span>}
        <span className={`badge s-${r.status}`}>{STATUS_LABEL[r.status] || r.status}{r.queue_pos ? ` (#${r.queue_pos})` : ""}</span>
        {r.duration_sec ? <span className="muted">{fmtDur(r.duration_sec)}</span> : null}
        {r.recorded_at ? <span className="muted small-note">{r.recorded_at}</span> : null}
        <span className="spacer" />
        {r.kind !== "notes" && <button className="btn small" onClick={() => setListen(!listen)}>{listen ? "Hide" : "Listen"}</button>}
        {r.kind === "notes" && r.status === "done" && (
          <a className="btn small" href={`/api/recordings/${r.id}/file`} target="_blank" rel="noreferrer">View</a>
        )}
        <a className="btn small" href={`/api/recordings/${r.id}/file?dl=1`}>Download</a>
        {r.kind === "notes" && r.status === "done" && (
          <button className="btn small" onClick={() => onTranscript && onTranscript(r)}>Outline</button>
        )}
        {r.kind !== "notes" && r.status === "done" && (
          <>
            <button className="btn small" onClick={() => onTranscript && onTranscript(r)}>Transcript</button>
            {r.duration_sec >= 900 && (
              <button className="btn small" onClick={() => onSplit(r)} title="Cut this recording into separate class recordings">✂ Auto-split</button>
            )}
            <button className="btn small" onClick={reprocess}>↻ Re-process</button>
          </>
        )}
        {r.kind !== "notes" && (
          <select
          className="move-select"
          value={r.notebook_id ?? nbId}
          onChange={(e) => move(e.target.value)}
          title="Assign to class notebook"
        >
          {(notebooks || []).map((n) => (
            <option key={n.id} value={n.id}>{n.name}</option>
          ))}
          </select>
        )}
        <button className="icon-del" onClick={del} title="Delete recording">✕</button>
      </div>
      {active && (
        <>
          {r.note && <div className="muted small-note" style={{ marginTop: 4 }}>{r.note}</div>}
          <div className="progress"><div className="bar" style={{ width: `${Math.round(r.progress * 100)}%` }} /></div>
        </>
      )}
      {listen && (
        audioState === "ready"
          ? <audio controls autoPlay preload="none" src={`/api/recordings/${r.id}/audio`} style={{ width: "100%", marginTop: 6 }} />
          : <div className="muted small-note" style={{ marginTop: 6 }}>Preparing audio{audioState === "checking" ? "…" : " — big video file, extracting the audio track (one time)…"}</div>
      )}
      {r.status === "error" && <div className="err-text">{r.error}</div>}
    </div>
  );
}