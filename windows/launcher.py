"""StudyThing Windows launcher — the exe entry point.

Sets portable environment (data dir next to the exe, bundled ffmpeg +
whisper.cpp + model on PATH), starts the backend, opens the browser.
"""
import os
import sys
import threading
import time
import webbrowser


def _base() -> str:
    # PyInstaller onefile: bundled data lives under sys._MEIPASS;
    # writable/portable files live next to the exe.
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exe_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


def _setup_env() -> None:
    base = _base()
    exe_dir = _exe_dir()
    bin_dir = os.path.join(exe_dir, "bin")
    data_dir = os.path.join(exe_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    os.environ.setdefault("STUDY_DATA_DIR", data_dir)
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    wc_bin = os.path.join(bin_dir, "whisper-cli.exe")
    wc_model = os.path.join(bin_dir, "ggml-large-v3-turbo-q5_0.bin")
    if os.path.exists(wc_bin):
        os.environ.setdefault("STUDY_ASR_BACKEND", "whisper.cpp")
        os.environ.setdefault("STUDY_WHISPERCPP_BIN", wc_bin)
        if os.path.exists(wc_model):
            os.environ.setdefault("STUDY_WHISPERCPP_MODEL", wc_model)
    # friendly starter .env next to the exe (only if missing)
    env_path = os.path.join(exe_dir, ".env")
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(
                "# StudyThing settings\n"
                "# Pick ONE brain option:\n"
                "#   1) Local brain (private): install Ollama from https://ollama.com\n"
                "#      then run:  ollama pull qwen3:8b\n"
                "#   2) Cloud brain: get a key at https://openrouter.ai/keys and add:\n"
                '# OPENROUTER_API_KEY=sk-or-...\n'
                '# STUDY_LLM_PROVIDER=openrouter\n'
                '# STUDY_OPENROUTER_MODEL=google/gemini-2.5-flash\n'
            )


def _main() -> None:
    _setup_env()
    port = 8765
    import socket

    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        port = 8766
    finally:
        s.close()
    url = f"http://localhost:{port}"
    threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    print(f"\n  StudyThing running at {url}  (close this window to quit)\n")
    import uvicorn  # noqa: E402
    from backend.main import app  # noqa: E402

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    _main()
