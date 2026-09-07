# StudyThing — Reference Documentation

Local-first study app: turn lecture recordings, notes, and slides into flashcards.
Everything runs on your own machine. Nothing leaves it unless you explicitly use the
share link or a cloud LLM provider.

---

## 1. Concepts

| Concept | What it is |
|---|---|
| **Notebook** | One class (e.g. "Chemistry 1"). Holds recordings, decks, quizzes, reviewers. |
| **Recording** | Audio file, or a notes file (PDF / images / docx). Audio → transcribed locally; notes → read by a vision AI into a **lesson outline**. Both are stored as "transcript" chunks used by everything downstream. |
| **Suggest inbox (escrow)** | Uploaded recordings without a class go here. The classifier *suggests* a notebook + confidence; **you approve**. Nothing is ever auto-filed. |
| **Test (quiz schedule)** | A test announcement (date + scope) scanned from transcripts. Scope must be **confirmed** before decks can generate. |
| **Deck** | Flashcard set for a confirmed test's scope. Generation is a background LLM job; cards land as a **suggestion** you confirm before studying. |
| **Study / SRS** | Study a deck with spaced repetition (Again / Hard / Good / Easy ratings). |
| **Reviewer** | Printable/downloadable review document per notebook. |
| **Focus** | Weak-spot practice view per notebook (low-rated cards). |
| **Share link** | Temporary public URL via a cloudflared tunnel — workaround for viewing outside your machine, opt-in only. |

### Pipeline (one recording, in order)
`denoise (ffmpeg) → split → transcribe (whisper.cpp or faster-whisper) → classify (LLM suggests notebook, escrow) → done`
Notes: `images/PDF pages → vision LLM outline (or OCR fallback) → classify → done`
Then, only on your explicit action: test scan → confirm scope → deck generate → confirm cards → study/SRS.

---

## 2. Quick start

### macOS (dev)
```bash
./run-dev.sh          # backend :8765 + Vite frontend :5173, open http://localhost:5173
```
Setup: `./setup.sh`, config in `.env` (see §8). Whisper model at
`data/models/ggml-large-v3-turbo-q5_0.bin`.

### Windows (one-click, for friends)
1. Download `StudyThing-windows.zip` from the GitHub Releases page.
2. Unzip → double-click `StudyThing.exe` → browser opens.
3. One-time brain setup (see `START-HERE.txt`): install Ollama + `ollama pull qwen3:8b`, **or** paste an OpenRouter key into `.env`.
SmartScreen warning on first launch is normal (unsigned exe): *More info → Run anyway*.

---

## 3. UI map (every button)

### Sidebar (always visible)
| Control | Does |
|---|---|
| **Suggest notebook** | Opens the escrow inbox (unclassified recordings; assign/re-classify). |
| **Quiz schedule** | Cross-notebook schedule of upcoming tests + confirmed scopes. |
| **Notebook rows** | Click → notebook view. Shows rec/card counts. Hover: open. |
| **New class notebook… + [+]** | Create notebook modal (name + topics; optional syllabus text — parsed for tests). |
| **Share link** | Panel: starts cloudflared tunnel, copy public URL, Stop. |
| **Dark mode / Light mode** | Theme toggle. Persisted; first visit follows system preference. |

### Home (landing page)
| Control | Does |
|---|---|
| **Stat tiles** (classes/recordings/flashcards/decks/quizzes/inbox) | Big numbers; inbox tile clicks through to Suggest inbox. |
| **Inbox callout** | Shows when transcriptions wait for assignment → click to open inbox. |
| **Processing section** | Live queue progress bar (auto-refreshes every 3s). |
| **Upcoming tests → "Quiz schedule"** | Jumps to schedule view. Test rows click through to notebook; badge = scheduled / awaiting scope. |
| **Recent recordings rows** | Click name → notebook. Date + status badge per row. |
| **＋ New notebook** | Create modal (empty state only). |

### Notebook view
| Control | Does |
|---|---|
| **Drop zone / upload** | Add audio (m4a mp3 wav webm mp4 aac ogg) or notes (pdf png jpg jpeg heic docx txt md). Audio + notes accepted anywhere; notes run through the vision outline path. |
| **Rename / edit topics** | Pencil controls; also edits recording metadata. |
| **Delete** | Per-recording and per-notebook; ask-confirm dialog. |
| **Re-classify** | Sends a recording back to the classifier suggestion. |
| **Reprocess** | Wipes the row's cards/chunks and re-runs the pipeline from scratch. |
| **Listen / Hide** | Streams audio with seek + Range (recordings only — hidden for notes). |
| **Transcript** | Modal with the full transcript/outline text. |
| **Tests section** | Scanned test announcements: confirm date + scope; "Make deck" generates cards for confirmed scope; delete. |
| **Decks section** | Deck cards with generated-card suggestions; Confirm → becomes studyable; Export (Anki `.apkg` / CSV); delete. |
| **Study** | SRS session on a confirmed deck; rate cards; progress persists. |
| **Quizzes** | Generate a practice quiz from deck/scope; take it; delete. |
| **Focus** | Weak-card practice; **Auto-focus** builds a focus set. |
| **Reviewers** | Create reviewer doc; view/download (docx); delete. |
| **Full transcript** | Concatenated notebook transcript view. |

### Global
| Control | Does |
|---|---|
| **Stop all** (top bar, only when processing) | Marks every active recording + generating deck as stopped; in-flight jobs abort at their next stage boundary (~1 min worst case). |
| **Progress bar** (top) | Mean progress of active recordings + per-row badges. |

---

## 4. HTTP API (all under `/api`)

**System:** `GET /health` · `GET /llm/status` (provider, model, ollama running) · `GET /processing` (busy, recordings, progress) · `POST /jobs/stop`

**Home:** `GET /home` (totals + recent 6 recordings + next 6 tests)

**Notebooks:** `GET /notebooks` · `POST /notebooks` · `GET|PATCH|DELETE /notebooks/{id}` · `POST /notebooks/parse-syllabus` (LLM extracts tests from syllabus text) · `GET /notebooks/{id}/study` (SRS queue) · `GET /notebooks/{id}/cards` · `GET /notebooks/{id}/transcript` (concatenated)

**Recordings:** `GET /inbox` · `GET /inbox/count` · `POST /inbox/recordings` · `POST /notebooks/{id}/recordings` · `GET /recordings/{id}` · `PATCH /recordings/{id}` (rename) · `DELETE /recordings/{id}` · `POST /recordings/{id}/reprocess` · `POST /recordings/{id}/reclassify` · `POST /recordings/{id}/assign` (approve escrow → notebook) · `GET /recordings/{id}/cards` · `GET /recordings/{id}/transcript` · `GET /recordings/{id}/audio` (Range streaming) · `GET /recordings/{id}/export` (csv)

**Tests:** `GET /schedule` (all notebooks) · `POST /schedule/scan` (LLM scans transcripts for announcements) · `GET|POST /notebooks/{id}/tests` (+`/scan`) · `POST /tests/{id}/deck` (generate deck from scope) · `POST /tests/{id}/confirm` · `DELETE /tests/{id}`

**Decks:** `GET|POST /notebooks/{id}/decks` · `POST /decks/{id}/guess` (LLM suggests cards) · `POST /decks/{id}/confirm` · `PATCH /decks/{id}` (edit scope) · `DELETE /decks/{id}` · `GET /decks/{id}/export?format=apkg|csv`

**Quizzes:** `GET|POST /notebooks/{id}/quizzes` · `GET|DELETE /quizzes/{id}`

**SRS:** `POST /ratings` (again/hard/good/easy)

**Focus/Reviewers:** `GET /notebooks/{id}/focus` · `POST /notebooks/{id}/auto-focus` · `GET|POST /notebooks/{id}/reviewers` · `GET|DELETE /reviewers/{id}` · `GET /reviewers/{id}/download`

**Tunnel (share):** `GET /tunnel` (status/url) · `POST /tunnel/start` · `POST /tunnel/stop`

---

## 5. Data layout

```
data/
  studything.db          SQLite (notebooks, recordings, cards, decks, tests, quizzes, ratings)
  audio/                 uploads (originals + work dirs)
  models/                whisper.cpp ggml model
  backups/               (if enabled)
frontend/dist/           built web UI (served by backend at /)
```
Backup = copy `data/`. Delete a notebook → its recordings/cards/decks cascade (confirm dialog guards).

---

## 6. Background jobs & failure modes

- Serial worker: one recording processes at a time (memory-bound, no parallelism).
- Jobs are cancellable: Stop all → clean abort at stage boundaries.
- Reprocess is destructive to that row's cards/chunks (intentional).
- LLM calls are background tasks with bounded retries; failures surface in job status/`note`, never block the UI.
- Classification failures leave the recording in the inbox (escrow), never misfiled.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| "Ollama not running" | Open the Ollama app; check `GET /api/llm/status`. |
| Transcription slow on Windows | AMD/Intel → Vulkan whisper.cpp is auto-selected; NVIDIA GPUs use CUDA faster-whisper. |
| Upload button does nothing | Allowed extensions: audio + pdf/png/jpg/jpeg/heic/docx/txt/md. |
| Port already in use | Backend tries 8765 then 8766 (launcher) / free the port for dev. |
| Friends see SmartScreen warning | Unsigned exe — More info → Run anyway. |

## 8. Configuration (`.env`, next to the repo or next to the exe)

| Var | Meaning | Default |
|---|---|---|
| `STUDY_ASR_BACKEND` | `whisper.cpp` or `faster-whisper` | auto (whisper.cpp on Apple Silicon) |
| `STUDY_WHISPERCPP_BIN` | whisper-cli path | PATH / bundled bin |
| `STUDY_WHISPERCPP_MODEL` | ggml model path | `data/models/ggml-large-v3-turbo-q5_0.bin` |
| `STUDY_WHISPER_MODEL` | faster-whisper model name | `large-v3-turbo` (Windows CUDA) |
| `STUDY_LLM_PROVIDER` | `ollama` or `openrouter` | `ollama` |
| `STUDY_OLLAMA_MODEL` | local model tag | `qwen3:8b` |
| `OPENROUTER_API_KEY` | cloud LLM key | — |
| `STUDY_OPENROUTER_MODEL` | cloud model id | `google/gemini-2.5-flash` |
| `STUDY_OPENROUTER_VISION_MODEL` | vision model for notes outlines | `google/gemini-2.5-flash` |
| `STUDY_DATA_DIR` | where data/ lives (Windows exe sets this) | repo `data/` |

## 9. Privacy

- Audio, DB, everything on your disk. Tunnel only when you start it.
- LLM: local Ollama = nothing leaves. OpenRouter = transcript text + slide images go to the model you choose.
- Share links: temporary, generated on demand, stopped from the Share panel.
