async function j(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return res.json();
}

export const api = {
  health: () => fetch("/api/health").then(j),
  notebooks: () => fetch("/api/notebooks").then(j),
  createNotebook: (name) =>
    fetch("/api/notebooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then(j),
  deleteNotebook: (id) => fetch(`/api/notebooks/${id}`, { method: "DELETE" }).then(j),
  notebook: (id) => fetch(`/api/notebooks/${id}`).then(j),
  cards: (nbId) => fetch(`/api/notebooks/${nbId}/cards`).then(j),
  upload: (nbId, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/notebooks/${nbId}/recordings`, { method: "POST", body: fd }).then(j);
  },
  deleteRecording: (id) => fetch(`/api/recordings/${id}`, { method: "DELETE" }).then(j),
};