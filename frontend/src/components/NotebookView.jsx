import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Outline from "./Outline.jsx";
import QuizModal from "./QuizModal.jsx";
import QuizView from "./QuizView.jsx";
import FocusView from "./FocusView.jsx";
import TranscriptModal from "./TranscriptModal.jsx";
import { askConfirm } from "../confirm.js";

const STATUS_LABEL = {
  queued: "Queued",
  denoising: "Cleaning audio",
  splitting: "Splitting",
  transcribing: "Transcribing",
  reading: "Reading notes",
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
  const [reviewers, setReviewers] = useState([]);
  const [revBusy, setRevBusy] = useState(false);
  const [revTopic, setRevTopic] = useState("__all__");
  const [openRev, setOpenRev] = useState(null); // reviewer id expanded
  const [revContent, setRevContent] = useState(null);
  const [tests, setTests] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [quizzes, setQuizzes] = useState([]);
  const [quizModal, setQuizModal] = useState(false);
  const [activeQuiz, setActiveQuiz] = useState(null); // {id, title}
  const [autoFocusing, setAutoFocusing] = useState(false);
  const [srcTab, setSrcTab] = useState("recordings");
  const [selTopic, setSelTopic] = useState(null);
  const [decks, setDecks] = useState([]);
  const [scopeModal, setScopeModal] = useState(null); // deck being confirmed
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
      setTranscriptModal({ title: `Transcript — ${r.original_name}`, data: { recordings: [{ id: r.id, name: r.original_name, duration_sec: r.duration_sec, chunks: t.chunks }] } });
    } catch (e) { alert(e.message); }
  };

  const load = useCallback(async () => {
    try {
      const [n, rvs, ts, qzs, dks, fc] = await Promise.all([
        api.notebook(notebookId), api.reviewers(notebookId), api.tests(notebookId), api.quizzes(notebookId), api.decks(notebookId), api.focus(notebookId),
      ]);
      setNb(n);
      setReviewers(rvs);
      setTests(ts);
      setQuizzes(qzs);
      setDecks(dks);
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

  const startStudy = async () => {
    const q = await api.study(notebookId);
    if (!q.cards.length) return alert("Nothing due — all cards scheduled. Study again when the queue fills up.");
    onStudy(nb.name);
  };

  const editTopics = () => {
    onEditFocus(nb);
  };

  const newDeck = async () => {
    // fully automatic: guess scope from notebook topics, generate immediately
    const dk = await api.createDeck(notebookId, { title: "Full syllabus" });
    const { scope } = await api.guessDeckScope(dk.id);
    await api.updateDeck(dk.id, { scope });
    await api.confirmDeck(dk.id);
    load();
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

  const topicOptions = (nb?.topics || "")
    .split("\n")
    .map((t) => t.trim())
    .filter(Boolean);

  const genReviewer = async () => {
    setRevBusy(true);
    try {
      const created = await api.createReviewer(notebookId, revTopic);
      await load();
      setOpenRev(created.id);
      setRevContent(created.content);
    } catch (ex) {
      alert(ex.message);
    }
    setRevBusy(false);
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

  const makeQuiz = async (source, difficulty, num) => {
    const q = await api.createQuiz(notebookId, { source: label(source), scope: scopeList(source), difficulty, num_questions: num });
    await load();
    setActiveQuiz({ id: q.id, title: q.title });
  };

  const label = (src) => {
    if (src === "__all__") return "All cards";
    if (src.startsWith("topic:")) return src.slice(6);
    return tests.find((x) => `test:${x.id}` === src)?.title || src;
  };
  const scopeList = (src) => {
    if (src === "__all__") return [];
    if (src.startsWith("topic:")) return [src.slice(6)];
    return tests.find((x) => `test:${x.id}` === src)?.scope || [];
  };

  const delQuiz = async (id) => {
    if (!(await askConfirm("Delete this quiz?"))) return;
    await api.deleteQuiz(id);
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
          <button className="btn" onClick={() => editTopics()}>Focus</button>
          <button className="primary" onClick={startStudy}>
            ▶ Study{(nb.due_count || nb.new_count) ? ` (${nb.due_count} due · ${nb.new_count} new)` : ""}
          </button>
          <a className="btn" href={`/api/notebooks/${nb.id}/export?format=apkg`}>Export Anki</a>
          <a className="btn" href={`/api/notebooks/${nb.id}/export?format=csv`}>Export CSV</a>
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
          accept="audio/*,video/mp4,.m4a,.mp3,.wav,.webm,.mov"
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
          <RecordingRow key={r.id} r={r} onChanged={load} onStudy={onStudy} nbName={nb.name} notebooks={notebooks} onTranscript={openRecTranscript} />
        ))}
      </section>
      </section>

      <section className="rev-section">
        <div className="rev-bar">
          <h4>Flashcard decks</h4>
          <button className="btn small" onClick={newDeck}>＋ Auto-generate deck</button>
        </div>
        {decks.length === 0 && <p className="muted small-note">No decks yet. Decks generate automatically when a test is detected in your recordings — or click the button to build one from the full syllabus.</p>}
        {decks.map((dk) => (
          <DeckRow key={dk.id} dk={dk} onChanged={load} onStudy={onStudy} nbName={nb.name} notebookId={notebookId} onConfirmScope={(d) => setScopeModal(d)} />
        ))}
      </section>

      <section className="rev-section">
        <div className="rev-bar">
          <h4>Reviewers</h4>
          <select value={revTopic} onChange={(e) => setRevTopic(e.target.value)} disabled={revBusy}>
            <option value="__all__">All topics</option>
            {topicOptions.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button className="btn primary" onClick={genReviewer} disabled={revBusy}>
            {revBusy ? "Writing…" : "＋ Generate reviewer"}
          </button>
        </div>
        {reviewers.length === 0 && <p className="muted small-note">No reviewers yet — generate a study guide from a topic's flashcards.</p>}
        {reviewers.map((rv) => (
          <div key={rv.id} className="rev-row">
            <button className="rev-main" onClick={() => toggleRev(rv.id)}>
              <span className="rev-topic">{rv.topic}</span>
              <span className="muted">{rv.created_at.slice(0, 16).replace("T", " ")} · {Math.round(rv.chars / 100) / 10}k chars</span>
            </button>
            <a className="btn small" href={`/api/reviewers/${rv.id}/download?format=md`}>.md</a>
            <a className="btn small" href={`/api/reviewers/${rv.id}/download?format=txt`}>.txt</a>
            <button className="icon-del" onClick={() => delRev(rv.id)} title="Delete reviewer">✕</button>
            {openRev === rv.id && (
              <div className="rev-body">
                <Outline content={revContent} />
              </div>
            )}
          </div>
        ))}
      </section>

      <section className="rev-section quizzes-section">
        <div className="rev-bar">
          <h4>Quizzes</h4>
          <button className="btn primary" onClick={() => setQuizModal(true)}>＋ New quiz</button>
        </div>
        {quizzes.length === 0 && <p className="muted small-note">Practice tests built from your flashcards — scope them to a test from the schedule, difficulty 1-10.</p>}
        {quizzes.map((qz) => (
          <div key={qz.id} className="quiz-row">
            <button className="rev-main" onClick={() => setActiveQuiz({ id: qz.id, title: qz.title })}>
              <span className="rev-topic">{qz.title}</span>
              <span className="muted">{qz.created_at.slice(0, 16).replace("T", " ")}</span>
            </button>
            <button className="icon-del" onClick={() => delQuiz(qz.id)} title="Delete quiz">✕</button>
          </div>
        ))}
      </section>

      {scopeModal && <ScopeModal deck={scopeModal} onClose={() => setScopeModal(null)} />}
      {transcriptModal && <TranscriptModal title={transcriptModal.title} data={transcriptModal.data} onClose={() => setTranscriptModal(null)} />}
      {quizModal && (
        <QuizModal
          tests={tests}
          topicOptions={topicOptions}
          onSave={makeQuiz}
          onClose={() => setQuizModal(false)}
        />
      )}
      {activeQuiz && (
        <QuizView quizId={activeQuiz.id} title={activeQuiz.title} onClose={() => setActiveQuiz(null)} />
      )}
    </div>
  );
}

function ScopeModal({ deck, onSave, onClose }) {
  const [scopeText, setScopeText] = useState((deck.scope || []).join("\n"));
  const [guessing, setGuessing] = useState(false);

  const guess = async () => {
    setGuessing(true);
    try {
      const r = await api.guessDeckScope(deck.id);
      setScopeText(r.scope.join("\n"));
    } catch (e) {
      alert(e.message);
    }
    setGuessing(false);
  };

  const save = async () => {
    const scope = scopeText.split("\n").map((s) => s.trim()).filter(Boolean);
    await api.updateDeck(deck.id, { scope });
    await api.confirmDeck(deck.id);
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Confirm scope — {deck.title}</h3>
        <label>Scope <span className="muted">(flashcards will only cover these)</span></label>
        <textarea rows={7} value={scopeText} onChange={(e) => setScopeText(e.target.value)}
                  placeholder={"One scope topic per line.\nThe guess below is auto-generated from the test announcement + syllabus — edit freely."} />
        <div className="modal-actions">
          <button className="btn" onClick={guess} disabled={guessing}>{guessing ? "Guessing…" : "⟳ Auto-guess scope"}</button>
          <span className="spacer" />
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>Confirm → generate flashcards</button>
        </div>
      </div>
    </div>
  );
}

function DeckRow({ dk, onChanged, onStudy, nbName, notebookId, onConfirmScope }) {
  const [browse, setBrowse] = useState(null); // cards of this deck
  const active = dk.status === "generating";

  const studyThis = async () => {
    const q = await api.study(notebookId, null, null, dk.id);
    if (!q.cards.length) return alert("Nothing due in this deck yet.");
    onStudy(dk.title, null, null, dk.id);
  };

  const del = async () => {
    if (!(await askConfirm(`Delete deck "${dk.title}" and its ${dk.card_count} flashcards?`))) return;
    await api.deleteDeck(dk.id);
    onChanged();
  };

  const toggle = async () => {
    if (browse === null) {
      const c = await api.cards(notebookId, null, dk.id);
      setBrowse(c.cards);
    } else setBrowse(null);
  };

  return (
    <div className="rec-row deck-row">
      <div className="rec-top">
        <button className="rec-toggle" onClick={toggle}>{browse !== null ? "▾" : "▸"}</button>
        <span className="rec-name">{dk.title}</span>
        <span className={`badge s-${dk.status === "ready" ? "done" : dk.status === "error" ? "error" : dk.status}`}>{dk.status}</span>
        <span className="muted">{dk.card_count} cards</span>
        <span className="spacer" />
        {(dk.status === "draft" || dk.status === "ready" || dk.status === "error") && (
          <button className="btn small primary" onClick={() => onConfirmScope(dk)}>
            {dk.status === "draft" ? "Confirm scope" : "Edit scope"}
          </button>
        )}
        {dk.status === "ready" && (
          <>
            <button className="btn small" onClick={studyThis}>▶ Study</button>
            <a className="btn small" href={`/api/decks/${dk.id}/export?format=apkg`}>Anki</a>
            <a className="btn small" href={`/api/decks/${dk.id}/export?format=csv`}>CSV</a>
          </>
        )}
        {active && <span className="muted small-note">generating…</span>}
        <button className="icon-del" onClick={del} title="Delete deck">✕</button>
      </div>
      {dk.scope && dk.scope.length > 0 && (
        <div className="muted small-note" style={{ marginTop: 6 }}>Scope: {dk.scope.join(" · ")}</div>
      )}
      {browse !== null && (
        <div className="cards" style={{ marginTop: 10 }}>
          {browse.length === 0 && <p className="muted">No cards.</p>}
          {browse.map((c) => (
            <details key={c.id} className="card">
              <summary>{c.question}</summary>
              <p>{c.answer}</p>
              {c.topic && <div className="muted small-note">{c.topic}</div>}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

function RecordingRow({ r, onChanged, onStudy, nbName, notebooks, onTranscript }) {
  const active = ACTIVE.has(r.status);

  const del = async () => {
    if (!(await askConfirm(`Delete "${r.original_name}" and its flashcards?`))) return;
    await api.deleteRecording(r.id);
    onChanged();
  };

  const move = async (notebookId) => {
    if (!notebookId || Number(notebookId) === r.notebook_id) return;
    await api.moveRecording(r.id, Number(notebookId));
    onChanged();
  };

  const reprocess = async () => {
    if (!(await askConfirm("Re-run transcription + flashcard generation for this recording? (existing cards are rebuilt)"))) return;
    await api.reprocess(r.id);
    onChanged();
  };

  return (
    <div className="rec-row">
      <div className="rec-top">
        <span className="rec-name">{r.original_name}</span>
        {r.kind === "notes" && <span className="badge">Notes</span>}
        <span className={`badge s-${r.status}`}>{STATUS_LABEL[r.status] || r.status}{r.queue_pos ? ` (#${r.queue_pos})` : ""}</span>
        {r.duration_sec ? <span className="muted">{fmtDur(r.duration_sec)}</span> : null}
        <span className="spacer" />
        {r.status === "done" && (
          <>
            <button className="btn small" onClick={() => onTranscript && onTranscript(r)}>Transcript</button>
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
    </div>
  );
}