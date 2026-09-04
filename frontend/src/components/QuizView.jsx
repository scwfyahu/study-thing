import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function QuizView({ quizId, title, onClose }) {
  const [quiz, setQuiz] = useState(null);
  const [idx, setIdx] = useState(0);
  const [picked, setPicked] = useState(null); // index chosen
  const [score, setScore] = useState(0);
  const [finished, setFinished] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.quiz(quizId).then(setQuiz).catch((e) => setErr(e.message));
  }, [quizId]);

  if (err) return <div className="empty"><p className="banner error">{err}</p><button className="btn" onClick={onClose}>← Back</button></div>;
  if (!quiz) return <div className="loading">Loading quiz…</div>;

  const questions = quiz.questions;
  const q = questions[idx];

  const pick = (i) => {
    if (picked !== null) return;
    setPicked(i);
    if (i === q.answer_index) setScore((s) => s + 1);
  };

  const next = () => {
    if (idx + 1 >= questions.length) setFinished(true);
    else { setIdx(idx + 1); setPicked(null); }
  };

  if (finished) {
    const pct = Math.round((score / questions.length) * 100);
    return (
      <div className="study done">
        <h2>{score}/{questions.length} — {pct}%</h2>
        <p className="muted">{pct >= 80 ? "Solid. Move to a harder difficulty." : pct >= 50 ? "Halfway there — review the missed ones and retry." : "Review the flashcards for this scope, then try again."}</p>
        <div className="study-controls">
          <button className="btn" onClick={() => { setIdx(0); setPicked(null); setScore(0); setFinished(false); }}>↻ Retry</button>
          <button className="btn primary" onClick={onClose}>← Back</button>
        </div>
      </div>
    );
  }

  return (
    <div className="study">
      <header className="study-head">
        <button className="btn" onClick={onClose}>← Back</button>
        <h3>{title}</h3>
        <span className="muted">{idx + 1} / {questions.length} · score {score}</span>
      </header>
      <div className="quiz-q">
        <p className="question">{q.question}</p>
        <div className="quiz-choices">
          {q.choices.map((c, i) => {
            let cls = "quiz-choice";
            if (picked !== null) {
              if (i === q.answer_index) cls += " correct";
              else if (i === picked) cls += " wrong";
              else cls += " dim";
            }
            return (
              <button key={i} className={cls} onClick={() => pick(i)} disabled={picked !== null}>
                {String.fromCharCode(65 + i)}. {c}
              </button>
            );
          })}
        </div>
        {picked !== null && (
          <div className="quiz-feedback">
            <p className={picked === q.answer_index ? "fb good" : "fb bad"}>
              {picked === q.answer_index ? "✓ Correct" : `✗ Wrong — answer: ${String.fromCharCode(65 + q.answer_index)}`}
            </p>
            {q.explanation && <p className="muted">{q.explanation}</p>}
            <button className="btn primary" onClick={next}>{idx + 1 >= questions.length ? "See score" : "Next →"}</button>
          </div>
        )}
      </div>
    </div>
  );
}