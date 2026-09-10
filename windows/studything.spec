# PyInstaller spec: StudyThing Windows exe (onefile)
# Bundles the backend package + built frontend. Binary deps (ffmpeg,
# whisper-cli, ggml model) are added next to the exe by windows/build.ps1
# so the download stays small and users can swap models.
import os

block_cipher = None

datas = []
dist_dir = os.path.join(SPECPATH, "..", "frontend", "dist")
if os.path.isdir(dist_dir):
    datas.append((dist_dir, "frontend/dist"))
else:
    raise SystemExit("frontend/dist missing — build the frontend first")

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan.on",
        "backend.main",
        "anyio._backends._asyncio",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.f2py", "pyobjc", "mlx"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="StudyThing",
    console=True,          # keep the log window visible so users see the URL
    upx=False,
)
