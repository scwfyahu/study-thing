import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  const days = Math.ceil((d - new Date()) / 86400000);
  const label = d.toDateString().slice(0, 10);
  return days < 0 ? `${label} (${-days}d ago)` : days === 0 ? `${label} (today)` : `${label} (in ${days}d)`;
}

function DeckButton({ t, refresh, onConfirmScope }) {
  const [busy, setBusy] = useState(false);
  const status = t.deck_status;
  const go = async () => {
    setBusy(true);
    try { await api.testDeck(t.id); } catch {}
    await refresh();
    setBusy(false);
  };
  if (t.confirmed !== 1) {
    return <button className="btn small primary"
            onClick={() => onConfirmScope(t)}>Confirm scope</button>;
  }
  let label, cls = "btn small";
  if (busy) label = "Generating…";
  else if (!status) label = "Generate deck";
  else if (status === "ready") label = `Deck ready (${t.deck_cards || 0}) · Regenerate`;
  else label = "Deck: " + status + " · Regenerate";
  return <button className={cls + (status === "ready" ? " primary" : "")}
          onClick={go} disabled={busy}>{label}</button>;
}

function ScopeConfirm({ t, onClose, onDone }) {
  const [text, setText] = useState((t.scope || []).join("\n"));
  const [busy, setBusy] = useState(false);
  const [guessing, setGuessing] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [prefilled, setPrefilled] = useState(false);

  // auto-guess scope on open; keep retrying forever with visible feedback
  useEffect(() => {
    if (prefilled || (t.scope || []).length) { setPrefilled(true); return; }
    let alive = true, n = 0;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    (async () => {
      while (alive) {
        n += 1;
        setAttempt(n); setGuessing(true);
        try {
          const r = await api.guessTestScope(t.id);
          if (r && r.scope && r.scope.length) {
            setText(r.scope.join("\n")); setGuessing(false); return;
          }
        } catch {}
        setGuessing(false);
        await sleep(3000);
      }
    })();
    return () => { alive = false; };
  }, [t.id]);

  const confirm = async () => {
    setBusy(true);
    const scope = text.split("\n").map((s) => s.trim()).filter(Boolean);
    try { await api.confirmTest(t.id, scope); } catch {}
    await onDone(); onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Confirm scope — {t.title}</h3>
        <label>Scope <span className="muted">(flashcards will only cover these)</span></label>
        {guessing ? (
          <div className="loading" style={{ margin: "6px 0" }}>
            Guessing scope from syllabus + announcement… (attempt {attempt})
          </div>
        ) : attempt > 0 && (
          <p className="muted small-note" style={{ margin: "6px 0", color: "#e8b34b" }}>
            LLM busy — retrying… (attempt {attempt}). You can type the scope or confirm blank to use the full syllabus.
          </p>
        )}
        <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={"One topic per line. Leave blank to auto-guess from the syllabus + test announcement."} />
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={confirm} disabled={busy}>
            {busy ? "Confirming…" : "Confirm scope → generate deck"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ScheduleView({ onOpenNotebook }) {
  const [tests, setTests] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [err, setErr] = useState("");
  const [confirming, setConfirming] = useState(null);

  const load = useCallback(async () => {
    try {
      setTests(await api.schedule());
    } catch (e) {
      setErr(e.message);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const rescan = async () => {
    setScanning(true);
    try {
      await api.scanSchedule();
      await load();
    } catch (e) {
      setErr(e.message);
    }
    setScanning(false);
  };

  const del = async (id) => {
    await api.deleteTest(id);
    load();
  };

  const dated = (tests || []).filter((t) => t.date_iso);
  const undated = (tests || []).filter((t) => !t.date_iso);

  return (
    <div className="schedule">
      <header className="nb-head">
        <div>
          <h2>Quiz schedule</h2>
          <p className="muted small-note">All tests announced across your subjects — auto-scanned from transcripts.</p>
        </div>
        <div className="nb-actions">
          <button className="btn primary" onClick={rescan} disabled={scanning}>
            {scanning ? "Scanning all subjects…" : "⟳ Rescan all"}
          </button>
        </div>
      </header>
      {err && <div className="banner error">{err}</div>}
      {!tests && <div className="loading">Loading…</div>}
      {tests && tests.length === 0 && (
        <p className="muted">No tests announced yet. Upload recordings, then hit Rescan all.</p>
      )}

      {dated.length > 0 && (
        <>
          <h4 className="sched-group">Upcoming</h4>
          {dated.map((t) => (
            <div key={t.id} className="test-card dated">
              <div className="test-head">
                <span className="test-title">{t.title}</span>
                <button className="sched-subject" onClick={() => onOpenNotebook(t.notebook_id)}>
                  {t.notebook_name}
                </button>
                {t.date_text && <span className="test-date">{t.date_text}</span>}
                <span className="test-iso">{fmtDate(t.date_iso)}</span>
                <span className="spacer" />
                <DeckButton t={t} refresh={load} onConfirmScope={setConfirming} />
                <button className="icon-del" onClick={() => del(t.id)} title="Delete">✕</button>
              </div>
              {t.scope?.length > 0 && (
                <ul className="test-scope">
                  {t.scope.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              )}
            </div>
          ))}
        </>
      )}
      {undated.length > 0 && (
        <>
          <h4 className="sched-group">No date announced</h4>
          {undated.map((t) => (
            <div key={t.id} className="test-card">
              <div className="test-head">
                <span className="test-title">{t.title}</span>
                <button className="sched-subject" onClick={() => onOpenNotebook(t.notebook_id)}>
                  {t.notebook_name}
                </button>
                {t.date_text && <span className="test-date">“{t.date_text}”</span>}
                <span className="spacer" />
                <DeckButton t={t} refresh={load} onConfirmScope={setConfirming} />
                <button className="icon-del" onClick={() => del(t.id)} title="Delete">✕</button>
              </div>
              {t.scope?.length > 0 && (
                <ul className="test-scope">
                  {t.scope.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              )}
            </div>
          ))}
        </>
      )}
      {confirming && <ScopeConfirm t={confirming} onClose={() => setConfirming(null)} onDone={load} />}
    </div>
  );
}