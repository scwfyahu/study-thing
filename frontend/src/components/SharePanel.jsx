import { useEffect, useState } from "react";

export default function SharePanel() {
  const [url, setUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let t = null;
    const tick = async () => {
      try {
        const s = await fetch("/api/tunnel").then((r) => r.json());
        if (s.running && s.url) { setUrl(s.url); setBusy(false); }
        else if (busy && !s.url && s.running) { /* still resolving */ }
        else if (!s.running) setUrl(null);
      } catch { /* backend down */ }
    };
    const iv = setInterval(tick, 1500);
    tick();
    return () => clearInterval(iv);
  }, []);

  const start = async () => {
    setBusy(true);
    await fetch("/api/tunnel/start", { method: "POST" });
  };
  const stop = async () => {
    await fetch("/api/tunnel/stop", { method: "POST" });
    setUrl(null); setBusy(false);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); } catch {}
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="share-panel">
      {!url && !busy && (
        <button className="share-btn" onClick={start}>Share link</button>
      )}
      {busy && !url && (
        <div className="share-status">Starting tunnel…</div>
      )}
      {url && (
        <div className="share-box">
          <div className="share-url" title={url}>{url.replace("https://", "")}</div>
          <div className="share-actions">
            <button className="share-btn small" onClick={copy}>
              {copied ? "Copied ✓" : "Copy"}
            </button>
            <button className="share-btn small stop" onClick={stop}>Stop</button>
          </div>
          <div className="share-warn">public link — anyone with it can read your notes</div>
        </div>
      )}
    </div>
  );
}
