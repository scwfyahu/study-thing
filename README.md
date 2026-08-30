# StudyThing

A local-only NotebookLM clone that does **one thing**: turn raw class recordings into flashcards.

You drop in lecture recordings (noisy classroom audio included). StudyThing cleans the audio,
transcribes it on Apple Silicon (MLX Whisper), and generates flashcards with a local LLM
(Ollama). One **notebook** per class. Nothing ever leaves your Mac.

```
recording → ffmpeg (denoise + loudnorm, 16 kHz mono)
          → MLX Whisper (large-v3-turbo, GPU, chunked 10-min)
          → Ollama (qwen3:8b, strict JSON extraction per chunk)
          → merge + dedupe → flashcards
```

## Requirements

- **macOS** (Apple Silicon M1+): MLX Whisper GPU transcription (~15x realtime), 16 GB RAM is enough
- **Windows 10/11**: faster-whisper (CPU int8, NVIDIA CUDA used automatically if present) — slower than Mac, same features
- macOS: [Homebrew](https://brew.sh) · Windows: [winget](https://learn.microsoft.com/windows/package-manager/) + Python 3.11+

## Setup

**macOS:**

```bash
./setup.sh     # venv (python3.11) + brew deps + ollama model (~5 GB) + npm install
./run-dev.sh   # open http://localhost:5173
```

**Windows (PowerShell):**

```powershell
.\setup.ps1    # venv + winget deps + ollama model + npm install
.\run-dev.ps1  # open http://localhost:5173
```

If winget-installed tools aren't found, open a NEW terminal and re-run. Windows uses CPU int8 by default; an NVIDIA GPU (CUDA) is picked up automatically.

## Usage

1. Create a notebook per class (sidebar).
2. Drop recordings (m4a/mp3/wav/webm/mp4…) into the notebook. Processing starts automatically:
   **Cleaning audio → Transcribing → Making flashcards → Done.**
3. Click a recording to review its cards; hit **Study** to flip through them
   (Space = flip, ←/→ = navigate, mark "Got it" / "Not yet").
4. Export a recording or a whole notebook to **Anki (.apkg)** or **CSV**.
   CSV imports into Anki/Quizlet/Spreadsheets: columns `question,answer`.

## Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `STUDY_ASR_BACKEND` | `mlx` on Apple Silicon, `faster-whisper` elsewhere | Force the other with `mlx` / `faster-whisper`. |
| `STUDY_WHISPER_MODEL` | `large-v3-turbo` (per backend) | MLX: any `mlx-community/*` repo. faster-whisper: `large-v3-turbo`, `small`, `medium`… First run downloads the model. |
| `STUDY_WHISPER_LANGUAGE` | `en` | Set `auto` for auto-detect. |
| `STUDY_OLLAMA_MODEL` | `qwen3:8b` | Any Ollama model. Smaller: `qwen3:4b`, `llama3.1:8b`. |
| `STUDY_CHUNK_SECONDS` | `600` | Transcription/extraction chunk length. |
| `STUDY_MAX_CARDS` | `10` | Max cards extracted per 10-min chunk. |
| `STUDY_RNNOISE` | `data/rnnoise.rnn` | Drop an [RNNoise model](https://github.com/GregorR/rnnoise-models) here for stronger denoising than ffmpeg's built-in `afftdn`. |
| `STUDY_DATA_DIR` | `./data` | SQLite DB + audio storage. |

## Noisy-classroom tips

- The pipeline high-passes at 80 Hz, FFT-denoises (`afftdn`), and loudness-normalizes before ASR.
- For really bad recordings, drop an RNNoise model at `data/rnnoise.rnn` — it's meaningfully better on babble.
- Whisper still struggles when speech is quieter than background chatter; recording closer to the
  speaker (or a voice recorder with directional mic) beats any amount of post-processing.
- Check the **transcript** before trusting cards — see `GET /api/recordings/{id}/transcript`.

## Troubleshooting

- **"Failed" on a recording** — the error text is shown inline. Common causes: Ollama not running
  (`ollama serve` / `brew services start ollama`), model not pulled (`ollama pull qwen3:8b`),
  or a corrupt audio file.
- **Check system status** — `curl localhost:8765/api/health` shows whether mlx-whisper and Ollama
  are installed and which models are configured.
- **No speech found** — the recording may be too noisy/empty; try the RNNoise model or a cleaner source.

## Privacy

100% local: FastAPI + SQLite on `127.0.0.1`, MLX models on the GPU, Ollama on `localhost:11434`.
No telemetry, no cloud calls — the only network use is the one-time model downloads.