import { useEffect, useState } from "react";
import { api } from "../api.js";

// First-launch wizard: brain setup with zero text editing and zero terminal.
// Option 1: OpenRouter key pasted into the form (validated live).
// Option 2: Ollama — install link, auto-detect, background model pull with
//           live progress; wizard finishes itself.
export default function SetupView({ onDone }) {
  const [st, setSt] = useState(null);
  const [key, setKey] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.setupStatus().then(setSt).catch(() => {});
  }, []);
  useEffect(() => {
    const t = setInterval(() => {
      api.setupProgress().then(setProgress).catch(() => {});
    }, 2500);
    return () => clearInterval(t);
  }, []);
  const [pull, setPull] = useState(null);
  useEffect(() => {
    if (st && st.provider === "ollama" && st.ollama_has_model) onDone();
  }, [st]);  // eslint-disable-line

  const chooseCloud = async () => {
    setErr(""); setBusy(true);
    const r = await api.setupCloud(key);
    setBusy(false);
    if (r.ok) onDone();
    else setErr(r.error || "validation failed");
  };
  const chooseLocal = async () => {
    setErr(""); setBusy(true);
    const r = await api.setupLocal({});
    setBusy(false);
    setPull(r);
    if (!r.ok) setErr(r.error || "Ollama not detected yet");
  };

  return (
    <div className="setup">
      <h2>Welcome to StudyThing</h2>
      <p className="muted">One-time setup. Pick how the AI brain runs — everything else is already installed.</p>

      <div className="setup-option">
        <h3>Option A — Cloud brain (recommended to start)</h3>
        <p className="muted small-note">Works immediately. Your recordings stay on this machine; only the transcript text goes to the AI service.</p>
        <div className="setup-row">
          <input type="password" placeholder="sk-or-... (paste your key here)"
            value={key} onChange={(e) => setKey(e.target.value)} />
          <button className="btn primary" onClick={chooseCloud} disabled={busy || !key.trim()}>
            {busy ? "Checking…" : "Use this key"}
          </button>
          <a className="btn" href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">Get a free key ↗</a>
        </div>
      </div>

      <div className="setup-option">
        <h3>Option B — Local brain (fully private)</h3>
        {st && st.ollama_running && !st.ollama_has_model && (
          <>
            <p className="muted small-note">Ollama detected ✓. Now downloading the brain model (~5 GB, one time).</p>
            <div className="progress"><div className="bar" style={{ width: `${pull?.progress || 0}%` }} /></div>
            <button className="btn primary" onClick={chooseLocal} disabled={busy}>
              {busy ? "Starting…" : "Start download"}
            </button>
          </>
        )}
        {st && st.ollama_running && st.ollama_has_model && (
          <div>
            <p>Ollama + qwen3:8b detected ✓</p>
            <button className="btn primary" onClick={chooseLocal}>Use local brain</button>
          </div>
        )}
        {st && !st.ollama_running && (
          <>
            <p className="muted small-note">
              1) Click the button below to download and run the Ollama installer.
              {" "}2) When it finishes, open the Ollama app once.
              {" "}3) Come back to this tab — the wizard finishes automatically.
            </p>
            <div className="setup-row">
              <a className="btn" href={st.ollama_installer_url} target="_blank" rel="noreferrer">1. Get Ollama ↗</a>
              <button className="btn" onClick={() => { api.setupStatus().then(setSt).catch(() => {}); }}>
                2. I opened Ollama — check again
              </button>
            </div>
          </>
        )}
      </div>

      {err && <p className="err-text">{err}</p>}
      {pull?.error && <p className="err-text">Pull failed: {pull.error}</p>}
    </div>
  );
}
