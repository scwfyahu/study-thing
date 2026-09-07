import React, { useState } from "react";

// Rendering helper for the detailed Focus model: per-topic cards with weight
// (1-5 exam priority), summary, concrete subtopics, chapters and notes.
function Stars({ n }) {
  const v = Math.max(1, Math.min(5, n || 3));
  return <span className="focus-stars">{"★".repeat(v)}<span className="focus-stars-dim">{"★".repeat(5 - v)}</span></span>;
}

export default function FocusView({ focus, generating, onRegenerate, hasSyllabus }) {
  const [open, setOpen] = useState({});
  if (!focus?.length) {
    return (
      <div className="rev-section">
        <div className="rev-bar">
          <h4>Focus</h4>
          {hasSyllabus && (
            <button className="btn small" onClick={onRegenerate} disabled={generating}>
              {generating ? "Extracting…" : "⟳ Regenerate from syllabus"}
            </button>
          )}
        </div>
        <p className="muted small-note">
          {hasSyllabus ? "Generating detailed Focus from your syllabus…" : "No syllabus yet — upload one in Edit to build a detailed Focus."}
        </p>
      </div>
    );
  }

  const totalSubs = focus.reduce((a, t) => a + (t.subtopics?.length || 0), 0);
  const totalTerms = focus.reduce((a, t) => a + (t.key_terms?.length || 0), 0);

  return (
    <div className="rev-section">
      <div className="rev-bar">
        <h4>Focus <span className="muted small-note">· {focus.length} topics · {totalSubs} subpoints{totalTerms > 0 ? ` · ${totalTerms} key terms` : ""}</span></h4>
        {hasSyllabus && (
          <button className="btn small" onClick={onRegenerate} disabled={generating}>
            {generating ? "Extracting…" : "⟳ Regenerate from syllabus"}
          </button>
        )}
      </div>
      {focus.map((t) => (
        <details key={t.id} className="focus-topic" open={!!open[t.id]}
          onToggle={(e) => setOpen((o) => ({ ...o, [t.id]: e.target.open }))}>
          <summary>
            <span className="focus-name">{t.name}</span>
            {t.chapters && <span className="muted small-note"> · {t.chapters}</span>}
          </summary>
          <div className="focus-body">
            <div className="focus-meta">
              <Stars n={t.weight} /> <span className="muted small-note">priority {t.weight}/5</span>
            </div>
            {t.summary && <p className="focus-summary">{t.summary}</p>}
            {t.subtopics?.length > 0 && (
              <div className="focus-subs">
                {t.subtopics.map((s, i) => <span key={i} className="focus-chip">{s}</span>)}
              </div>
            )}
            {t.key_terms?.length > 0 && (
              <div className="focus-terms">
                <div className="focus-sec-h">Key terms</div>
                <dl>
                  {t.key_terms.map((k, i) => (
                    <div className="focus-term" key={i}><dt>{k.term}</dt><dd>{k.definition}</dd></div>
                  ))}
                </dl>
              </div>
            )}
            {t.exam_questions?.length > 0 && (
              <div className="focus-qs">
                <div className="focus-sec-h">Likely exam questions</div>
                <ul>{t.exam_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
              </div>
            )}
            {t.mistakes?.length > 0 && (
              <div className="focus-mistakes">
                <div className="focus-sec-h">Watch out</div>
                <ul>{t.mistakes.map((m, i) => <li key={i}>{m}</li>)}</ul>
              </div>
            )}
            {t.notes && <p className="muted small-note">⟳ {t.notes}</p>}
          </div>
        </details>
      ))}
    </div>
  );
}
