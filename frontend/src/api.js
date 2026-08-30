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
  createNotebook: (name, topics, syllabus) =>
    fetch("/api/notebooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, topics: topics || "", syllabus: syllabus || "" }),
    }).then(j),
  parseSyllabus: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/notebooks/parse-syllabus", { method: "POST", body: fd }).then(j);
  },
  deleteNotebook: (id) => fetch(`/api/notebooks/${id}`, { method: "DELETE" }).then(j),
  renameNotebook: (id, name) =>
    fetch(`/api/notebooks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then(j),
  setTopics: (id, topics) =>
    fetch(`/api/notebooks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topics }),
    }).then(j),
  moveRecording: (id, notebookId) =>
    fetch(`/api/recordings/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notebook_id: notebookId }),
    }).then(j),
  notebook: (id) => fetch(`/api/notebooks/${id}`).then(j),
  cards: (nbId) => fetch(`/api/notebooks/${nbId}/cards`).then(j),
  upload: (nbId, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/notebooks/${nbId}/recordings`, { method: "POST", body: fd }).then(j);
  },
  reprocess: (id) =>
    fetch(`/api/recordings/${id}/reprocess`, { method: "POST" }).then(j),
  deleteRecording: (id) => fetch(`/api/recordings/${id}`, { method: "DELETE" }).then(j),
  reviewers: (nbId) => fetch(`/api/notebooks/${nbId}/reviewers`).then(j),
  createReviewer: (nbId, topic) =>
    fetch(`/api/notebooks/${nbId}/reviewers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    }).then(j),
  deleteReviewer: (id) => fetch(`/api/reviewers/${id}`, { method: "DELETE" }).then(j),
  tests: (nbId) => fetch(`/api/notebooks/${nbId}/tests`).then(j),
  scanTests: (nbId) =>
    fetch(`/api/notebooks/${nbId}/tests/scan`, { method: "POST" }).then(j),
  deleteTest: (id) => fetch(`/api/tests/${id}`, { method: "DELETE" }).then(j),
  study: (nbId, recordingId) => {
    const q = recordingId ? `?recording_id=${recordingId}` : "";
    return fetch(`/api/notebooks/${nbId}/study${q}`).then(j);
  },
  rate: (cardId, rating) =>
    fetch("/api/ratings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: cardId, rating }),
    }).then(j),
  quizzes: (nbId) => fetch(`/api/notebooks/${nbId}/quizzes`).then(j),
  createQuiz: (nbId, body) =>
    fetch(`/api/notebooks/${nbId}/quizzes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j),
  quiz: (qid) => fetch(`/api/quizzes/${qid}`).then(j),
  deleteQuiz: (qid) => fetch(`/api/quizzes/${qid}`, { method: "DELETE" }).then(j),
};