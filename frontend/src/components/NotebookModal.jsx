import React, { useRef, useState } from "react";
import { api } from "../api.js";

export default function NotebookModal({ initial, onSave, onClose }) {
  const [name, setName] = useState(initial?.name || "");
  const [topics, setTopics] = useState(initial?.topics || "");
  const [syllabusText, setSyllabusText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parsedName, setParsedName] = useState("");
  const [err, setErr] = useState("");
  const fileInput = useRef(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await onSave(name.trim(), topics.trim(), syllabusText);
      onClose();
    } catch (ex) {
      setErr(ex.message);
    }
  };

  const parseFile = async (f) => {
    if (!f) return;
    setParsing(true);
    setErr("");
    try {
      const r = await api.parseSyllabus(f);
      setTopics(r.topics.join("\n"));
      setSyllabusText(r.text);
      setParsedName(f.name);
      if (!name.trim()) setName(f.name.replace(/\.(pdf|docx|txt|md)$/i, ""));
    } catch (ex) {
      setErr(ex.message);
    }
    setParsing(false);
  };

  const title = initial ? "Edit notebook" : "New class notebook";
  return (
    <div className="modal-overlay" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>{title}</h3>
        <label>Name</label>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
               placeholder="e.g. Biology, Life and Career Skills…" />

        {!initial && (
          <>
            <label>Study guide / syllabus <span className="muted">(PDF · DOCX · TXT — recommended)</span></label>
            <div
              className={"dropzone syl-zone" + (parsing ? " busy" : "")}
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); parseFile(e.dataTransfer.files[0]); }}
            >
              <input ref={fileInput} type="file" accept=".pdf,.docx,.txt,.md" hidden
                     onChange={(e) => { parseFile(e.target.files[0]); e.target.value = ""; }} />
              {parsing ? "Reading syllabus…" : parsedName ? `✓ ${parsedName} parsed — topics extracted below` : "Drop the syllabus here or click to browse"}
            </div>
          </>
        )}

        <label>Focus topics <span className="muted">(one per line — auto-filled from syllabus)</span></label>
        <textarea rows={5} value={topics} onChange={(e) => setTopics(e.target.value)}
                  placeholder={"Flashcards only cover these topics.\nIf no syllabus: paste topics manually, or leave empty for all content."} />

        {err && <div className="banner error">{err}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!name.trim()}>
            {initial ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}