import { useEffect, useState } from "react";
import { api } from "../api.js";
import { askConfirm } from "../confirm.js";

const fmtMin = (m) => `${Math.floor(m)}:${String(Math.round((m % 1) * 60)).padStart(2, "0")}`;

// Proposal editor: LLM-proposed class segments for a long cross-class
// recording. Fully editable before Apply — start/end are minutes.
export default function SplitModal({ rec, notebooks, preset, onClose, onDone }) {
  const [proposal, setProposal] = useState(preset || null);
  const [error, setError] = useState("");
  const [applying, setApplying] = useState(false);

  const retry = () => { setProposal(null); setError(""); api.splitPropose(rec.id).then((p) => setProposal(p)).catch((e) => setError(String(e.message || e))); };

  useEffect(() => {
    if (preset) return; // pre-computed proposal (auto-suggested on upload)
    let alive = true;
    setProposal(null); setError("");
    api.splitPropose(rec.id)
      .then((p) => alive && setProposal(p))
      .catch((e) => alive && setError(String(e.message || e)));
    return () => { alive = false; };
  }, [rec.id]);

  const setSeg = (i, field, value) => {
    setProposal((p) => {
      const segs = p.segments.map((s, j) => (j === i ? { ...s, [field]: value } : s));
      return { ...p, segments: segs };
    });
  };
  const removeSeg = (i) => setProposal((p) => ({ ...p, segments: p.segments.filter((_, j) => j !== i) }));
  const addSeg = () => setProposal((p) => {
    const last = p.segments[p.segments.length - 1];
    const start = last ? last.end_min : 0;
    return { ...p, segments: [...p.segments, { start_min: start, end_min: p.duration_min, title: "", notebook_id: null }] };
  });

  const apply = async () => {
    const segs = proposal.segments.map((s) => ({
      start_min: Number(s.start_min), end_min: Number(s.end_min),
      title: s.title, notebook_id: Number(s.notebook_id) || 0,
    }));
    if (!(await askConfirm(
      `Cut "${rec.original_name}" into ${segs.length} segment${segs.length > 1 ? "s" : ""}?\n` +
      "The original recording is removed; each part goes to the Suggest inbox for assignment."
    ))) return;
    setApplying(true);
    try {
      await api.splitApply(rec.id, segs);
      onDone(segs);
    } catch (e) {
      setError(String(e.message || e));
      setApplying(false);
    }
  };

  const totalMin = proposal
    ? proposal.segments.reduce((a, s) => a + (Number(s.end_min) - Number(s.start_min) || 0), 0)
    : 0;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal split-modal" onClick={(e) => e.stopPropagation()}>
        <h3>✂ Auto-split — {rec.original_name}</h3>
        {!proposal && !error && <p className="muted small-note">Analyzing the transcript for class boundaries…</p>}
        {error && <p className="err-text">{error}</p>}
        {proposal && proposal.segments.length === 0 && (
          <>
            <p className="err-text">Couldn't detect class boundaries — the model returned nothing usable. Try again (the free model is flaky; it may also genuinely be one single class).</p>
            <div className="modal-actions"><span className="spacer" /><button className="btn" onClick={retry}>⟳ Retry</button></div>
          </>
        )}
        {proposal && proposal.segments.length > 0 && (
          <>
            <p className="muted small-note">
              Proposed {proposal.segments.length} segment{proposal.segments.length > 1 ? "s" : ""} across {fmtMin(proposal.duration_min)} of recording.
              Edit boundaries (minutes) or assignments — nothing is cut until you apply.
            </p>
            <div className="split-rows">
              {proposal.segments.map((s, i) => (
                <div className="split-row" key={i}>
                  <input className="split-min" type="number" step="0.5" min="0"
                    value={s.start_min} onChange={(e) => setSeg(i, "start_min", e.target.value)} aria-label="start" />
                  <span className="muted">→</span>
                  <input className="split-min" type="number" step="0.5" min="0"
                    value={s.end_min} onChange={(e) => setSeg(i, "end_min", e.target.value)} aria-label="end" />
                  <input className="split-title" value={s.title || ""}
                    placeholder="Segment label" onChange={(e) => setSeg(i, "title", e.target.value)} />
                  <select value={s.notebook_id || ""} onChange={(e) => setSeg(i, "notebook_id", e.target.value ? Number(e.target.value) : null)}>
                    <option value="">Inbox (decide later)</option>
                    {(notebooks || []).map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                  </select>
                  {s.reason && <span className="muted small-note" title={s.reason}>{s.reason}</span>}
                  <button className="icon-del" onClick={() => removeSeg(i)} title="Remove segment">✕</button>
                </div>
              ))}
            </div>
            <p className="muted small-note">
              Covered: {Math.round(totalMin)} of {fmtMin(proposal.duration_min)} min.
              {totalMin < proposal.duration_min - 1 && " ⚠ some minutes are not covered by any segment."}
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={addSeg}>＋ Segment</button>
              <span className="spacer" />
              <button className="btn" onClick={onClose} disabled={applying}>Cancel</button>
              <button className="btn primary" onClick={apply} disabled={applying}>
                {applying ? "Cutting…" : "✂ Cut + send to inbox"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
