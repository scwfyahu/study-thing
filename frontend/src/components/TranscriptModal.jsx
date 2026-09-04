import React, { useMemo, useState } from "react";

function ts(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

// Shared transcript viewer: timestamped segments + live search.
// `data` shape: for a notebook → [{id,name,duration_sec,chunks:[{start_sec,text}]}]
//               for one recording → {chunks:[{start_sec,text}]} (wrapped by caller)
export default function TranscriptModal({ title, data, onClose }) {
  const [q, setQ] = useState("");
  const query = q.trim().toLowerCase();

  const recordings = useMemo(() => {
    const list = Array.isArray(data) ? data : (data?.recordings || []);
    if (!query) return list;
    return list
      .map((r) => ({
        ...r,
        chunks: (r.chunks || []).filter((c) => (c.text || "").toLowerCase().includes(query)),
      }))
      .filter((r) => r.chunks.length > 0);
  }, [data, query]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal transcript-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon-del" onClick={onClose} title="Close">✕</button>
        </div>
        <input
          className="transcript-search"
          placeholder="Search transcript…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus={false}
        />
        <div className="transcript-scroll">
          {recordings.length === 0 && (
            <p className="muted small-note">{query ? "No matches." : "No transcript yet."}</p>
          )}
          {recordings.map((rec) => (
            <div key={rec.id || "r"} className="transcript-group">
              <div className="transcript-source">{rec.name}{rec.duration_sec ? ` · ${ts(rec.duration_sec)}` : ""}</div>
              {(rec.chunks || []).map((c, i) => (
                <div className="transcript-line" key={i}>
                  <span className="transcript-ts">{ts(c.start_sec)}</span>
                  <span className="transcript-txt">{c.text}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
