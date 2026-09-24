import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import Outline from "./Outline.jsx";
import { askConfirm } from "../confirm.js";

function fmtDur(s) {
  if (!s) return "";
  const m = Math.floor(s / 60);
  return `${Math.floor(m / 60) ? `${Math.floor(m / 60)}h ` : ""}${m % 60}m`;
}

export default function ReviewerView({ notebooks, preselectNotebookId }) {
  const [nbId, setNbId] = useState(preselectNotebookId || "");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [topic, setTopic] = useState("");
  const [q, setQ] = useState("");
  const [pick, setPick] = useState({ recordings: [], topics: [] });
  const [selected, setSelected] = useState(new Set());
  const [title, setTitle] = useState("");
  const [building, setBuilding] = useState(false);
  const [guides, setGuides] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [openContent, setOpenContent] = useState(null);
  const [err, setErr] = useState("");

  const loadPick = useCallback(async () => {
    try {
      const r = await api.reviewerPick({
        notebook_id: nbId || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        topic: topic || undefined,
        q: q || undefined,
      });
      setPick(r);
      // drop selections that fell out of the filter
      setSelected((prev) => new Set([...prev].filter((id) =>
        r.recordings.some((x) => x.id === id))));
      setErr("");
    } catch (e) {
      setErr(e.message);
    }
  }, [nbId, dateFrom, dateTo, topic, q]);

  const loadGuides = useCallback(async () => {
    try { setGuides(await api.reviewers()); } catch { /* transient */ }
  }, []);

  useEffect(() => { loadPick(); }, [loadPick]);
  useEffect(() => {
    loadGuides();
    const t = setInterval(loadGuides, 3000);
    return () => clearInterval(t);
  }, [loadGuides]);

  const BUSY = (st) => st !== "ready" && st !== "error";
  const anyGenerating = guides.some((g) => BUSY(g.status));

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const generate = async () => {
    if (!selected.size) return;
    setBuilding(true);
    setErr("");
    try {
      await api.generateReviewer({
        recording_ids: [...selected],
        notebook_id: nbId || undefined,
        title: title.trim() || undefined,
      });
      setTitle("");
      await loadGuides();
    } catch (e) {
      setErr(e.message);
    }
    setBuilding(false);
  };

  const toggleOpen = async (g) => {
    if (openId === g.id) { setOpenId(null); setOpenContent(null); return; }
    setOpenId(g.id);
    setOpenContent(null);
    try {
      const r = await api.reviewer(g.id);
      setOpenContent(r.content || "");
    } catch (e) { setErr(e.message); }
  };

  const delGuide = async (g) => {
    if (!(await askConfirm(`Delete reviewer "${g.topic}"?`))) return;
    await api.deleteReviewer(g.id);
    if (openId === g.id) { setOpenId(null); setOpenContent(null); }
    loadGuides();
  };

  const allSelected = pick.recordings.length > 0 &&
    pick.recordings.every((r) => selected.has(r.id));

  return (
    <div className="notebook">
      <header className="nb-head">
        <div>
          <h2>Reviewer</h2>
          <div className="topics-line">Pick recordings by class, date and topic → study guide from their transcripts</div>
        </div>
      </header>

      <section className="rev-section">
        <div className="rev-bar"><h4>Pick recordings</h4></div>
        <div className="pick-filters">
          <select value={nbId} onChange={(e) => { setNbId(e.target.value); setTopic(""); }}>
            <option value="">All classes</option>
            {notebooks.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
          </select>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} title="From date" />
          <span className="muted">→</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} title="To date" />
          <select value={topic} onChange={(e) => setTopic(e.target.value)}>
            <option value="">Any topic</option>
            {pick.topics.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <input
            placeholder="Or type keywords…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        <div className="rev-bar" style={{ marginTop: 8 }}>
          <span className="muted small-note">{pick.recordings.length} matching · {selected.size} selected</span>
          <span className="spacer" />
          <button className="btn small" onClick={() => setSelected(allSelected ? new Set() : new Set(pick.recordings.map((r) => r.id)))}>
            {allSelected ? "None" : "All"}
          </button>
        </div>

        <div className="rec-list">
          {pick.recordings.length === 0 && (
            <p className="muted">No transcribed recordings match — widen the filters.</p>
          )}
          {pick.recordings.map((r) => (
            <div key={r.id} className="rec-row">
              <div className="rec-top">
                <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
                <span className="rec-name">{r.original_name}</span>
                <span className="muted small-note">{r.nb_name || "unassigned"}</span>
                <span className="muted small-note">{r.when_txt?.slice(0, 10)}</span>
                {r.duration_sec ? <span className="muted">{fmtDur(r.duration_sec)}</span> : null}
                <span className="muted small-note">{r.chunk_count} chunks</span>
              </div>
            </div>
          ))}
        </div>

        <div className="rev-bar" style={{ marginTop: 10 }}>
          <input
            placeholder="Reviewer title (optional)…"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            style={{ flex: 1, maxWidth: 380 }}
          />
          <span className="spacer" />
          <button className="btn primary" onClick={generate} disabled={building || !selected.size}>
            {building ? "Queueing…" : `▶ Generate reviewer${selected.size ? ` (${selected.size} rec)` : ""}`}
          </button>
        </div>
        {err && <p className="err-text">{err}</p>}
        <p className="muted small-note">
          The guide is built only from the selected recordings' transcripts plus Focus exam
          material, then each line is verified against the source (Jev) — unsupported lines get
          an [unverified] tag.
        </p>
      </section>

      <section className="rev-section">
        <div className="rev-bar">
          <h4>Saved reviewers</h4>
          {anyGenerating && <span className="muted small-note">building…</span>}
        </div>
        {guides.length === 0 && <p className="muted small-note">Nothing yet — pick recordings above.</p>}
        {guides.map((g) => (
          <div key={g.id} className="rev-row">
            <button className="rev-main" onClick={() => toggleOpen(g)}>
              <span className="rev-topic">{g.topic}</span>
              <span className={`badge s-${g.status === "ready" ? "done" : g.status === "error" ? "error" : g.status}`}>{g.status}</span>
              <span className="muted">{g.created_at.slice(0, 16).replace("T", " ")}{g.chars ? ` · ${Math.round(g.chars / 100) / 10}k chars` : ""}{g.source_ids?.length ? ` · ${g.source_ids.length} rec` : ""}</span>
            </button>
            <a className="btn small" href={`/api/reviewers/${g.id}/download?format=md`}>.md</a>
            <a className="btn small" href={`/api/reviewers/${g.id}/download?format=txt`}>.txt</a>
            <button className="icon-del" onClick={() => delGuide(g)} title="Delete reviewer">✕</button>
            {openId === g.id && (
              <div className="rev-body">
                {g.status === "error" && <p className="err-text">{g.error || "generation failed"}</p>}
                {g.status !== "ready" && g.status !== "error" && <p className="muted">Building — {g.status}. Refreshes automatically.</p>}
                {openContent ? <Outline content={openContent} /> : g.status === "ready" && <p className="muted">Loading…</p>}
              </div>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
