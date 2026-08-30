import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  const days = Math.ceil((d - new Date()) / 86400000);
  const label = d.toDateString().slice(0, 10);
  return days < 0 ? `${label} (${-days}d ago)` : days === 0 ? `${label} (today)` : `${label} (in ${days}d)`;
}

export default function ScheduleView({ onOpenNotebook }) {
  const [tests, setTests] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [err, setErr] = useState("");

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
                <span className="test-title">🗓 {t.title}</span>
                <button className="sched-subject" onClick={() => onOpenNotebook(t.notebook_id)}>
                  {t.notebook_name}
                </button>
                {t.date_text && <span className="test-date">{t.date_text}</span>}
                <span className="test-iso">{fmtDate(t.date_iso)}</span>
                <span className="spacer" />
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
                <span className="test-title">🗓 {t.title}</span>
                <button className="sched-subject" onClick={() => onOpenNotebook(t.notebook_id)}>
                  {t.notebook_name}
                </button>
                {t.date_text && <span className="test-date">“{t.date_text}”</span>}
                <span className="spacer" />
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
    </div>
  );
}