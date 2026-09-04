// In-app replacement for window.confirm(). Native confirm() is blocked /
// auto-denied inside iframes and embedded webviews (e.g. the SharePanel tunnel
// URL), which made every delete action silently "dead" there. This renders a
// real modal and resolves a promise, so it works anywhere the app renders.
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function askConfirm(message, title = "Are you sure?") {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "modal-overlay";
    wrap.innerHTML = `
      <div class="modal" style="max-width:440px">
        <h3>${esc(title)}</h3>
        <p style="margin:10px 0 18px;line-height:1.5">${esc(message)}</p>
        <div class="modal-actions">
          <span class="spacer" />
          <button class="btn cancel">Cancel</button>
          <button class="btn primary ok">Confirm</button>
        </div>
      </div>`;
    const close = (val) => {
      wrap.remove();
      document.removeEventListener("keydown", onKey);
      resolve(val);
    };
    const onKey = (e) => { if (e.key === "Escape") close(false); };
    wrap.querySelector(".cancel").onclick = () => close(false);
    wrap.querySelector(".ok").onclick = () => close(true);
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(false); });
    wrap.querySelector(".modal").addEventListener("click", (e) => e.stopPropagation());
    document.addEventListener("keydown", onKey);
    document.body.appendChild(wrap);
    wrap.querySelector(".ok").focus();
  });
}
