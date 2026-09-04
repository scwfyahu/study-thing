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
  updateNotebook: (id, body) =>
    fetch(`/api/notebooks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j),
  autoFocus: (id) => fetch(`/api/notebooks/${id}/auto-focus`, { method: "POST" }).then(j),
  focus: (id) => fetch(`/api/notebooks/${id}/focus`).then(j),
  moveRecording: (id, notebookId) =>
    fetch(`/api/recordings/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notebook_id: notebookId }),
    }).then(j),
  notebook: (id) => fetch(`/api/notebooks/${id}`).then(j),
  cards: (nbId, topic, deckId) => {
    const params = new URLSearchParams();
    if (topic) params.set("topic", topic);
    if (deckId) params.set("deck_id", deckId);
    const q = params.toString() ? `?${params}` : "";
    return fetch(`/api/notebooks/${nbId}/cards${q}`).then(j);
  },
  decks: (nbId) => fetch(`/api/notebooks/${nbId}/decks`).then(j),
  createDeck: (nbId, body) =>
    fetch(`/api/notebooks/${nbId}/decks`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then(j),
  guessDeckScope: (did) => fetch(`/api/decks/${did}/guess`, { method: "POST" }).then(j),
  updateDeck: (did, body) =>
    fetch(`/api/decks/${did}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then(j),
  confirmDeck: (did) => fetch(`/api/decks/${did}/confirm`, { method: "POST" }).then(j),
  deleteDeck: (did) => fetch(`/api/decks/${did}`, { method: "DELETE" }).then(j),
  upload: (nbId, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/notebooks/${nbId}/recordings`, { method: "POST", body: fd }).then(j);
  },
  bulkUpload: (files) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return fetch("/api/inbox/recordings", { method: "POST", body: fd }).then(j);
  },
  inbox: () => fetch("/api/inbox").then(j),
  inboxCount: () => fetch("/api/inbox/count").then(j),
  assign: (id, notebookId) =>
    fetch(`/api/recordings/${id}/assign`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notebook_id: notebookId }),
    }).then(j),
  reclassify: (id) => fetch(`/api/recordings/${id}/reclassify`, { method: "POST" }).then(j),
  transcript: (id) => fetch(`/api/recordings/${id}/transcript`).then(j),
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
  guessTestScope: (id, signal) => fetch(`/api/tests/${id}/guess`, {method:"POST", signal}).then(j),
  confirmTest: (id, scope) => fetch(`/api/tests/${id}/confirm`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({scope})}).then(j),
  testDeck: (id) => fetch(`/api/tests/${id}/deck`, { method: "POST" }).then(j),
  deleteTest: (id) => fetch(`/api/tests/${id}`, { method: "DELETE" }).then(j),
  schedule: () => fetch("/api/schedule").then(j),
  scanSchedule: () =>
    fetch("/api/schedule/scan", { method: "POST" }).then(j),
  study: (nbId, recordingId, topic, deckId) => {
    const params = new URLSearchParams();
    if (recordingId) params.set("recording_id", recordingId);
    if (topic) params.set("topic", topic);
    if (deckId) params.set("deck_id", deckId);
    const q = params.toString() ? `?${params}` : "";
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