import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function useAudioReady(recId, wanted) {
  // wanted = user pressed Listen for this recording
  const [state, setState] = useState(wanted ? "checking" : "idle");
  useEffect(() => {
    if (!wanted || !recId) { setState("idle"); return; }
    let alive = true;
    (async () => {
      try {
        for (;;) {
          const s = await api.audioStatus(recId);
          if (!alive) return;
          if (s.ready) { setState("ready"); return; }
          setState("preparing");
          await new Promise((r) => setTimeout(r, 3000));
        }
      } catch {
        if (alive) setState("ready"); // fall back to original file
      }
    })();
    return () => { alive = false; };
  }, [wanted, recId]);
  return wanted ? state : "idle";
}
