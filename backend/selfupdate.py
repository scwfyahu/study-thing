"""App self-update for the frozen Windows build.

Flow: GET /api/update  -> {available, latest, url, current}
      POST /api/update/install {url}
        -> download release zip to update-staging/, extract, write
           apply-update.bat (swap files, keep data/ + .env, restart exe),
           spawn the bat detached, exit.
Only meaningful when frozen (PyInstaller); on dev installs check works,
install returns 400.
"""
import json
import logging
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger("studything.selfupdate")

REPO = "scwfyahu/study-thing"


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def _app_dir() -> Path:
    """Where bundled data lives (onefile: sys._MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def current_version() -> str:
    for cand in (_exe_dir() / "version.txt", _app_dir() / "version.txt"):
        try:
            v = cand.read_text(encoding="utf-8", errors="replace").strip()
            if v:
                return v
        except OSError:
            continue
    return "dev"


def frozen() -> bool:
    return getattr(sys, "frozen", False)


def _semver(tag: str):
    m = None
    import re
    m = re.search(r"v(\d+)\.(\d+)\.(\d+)", tag or "")
    return tuple(map(int, m.groups())) if m else None


def latest_release() -> dict | None:
    """Newest non-draft release that ships StudyThing-windows.zip."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{REPO}/releases?per_page=10",
            timeout=15, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        for rel in r.json():
            if rel.get("draft"):
                continue
            for a in rel.get("assets") or []:
                if a.get("name") == "StudyThing-windows.zip":
                    return {
                        "tag": rel.get("tag_name"),
                        "url": a.get("browser_download_url"),
                    }
    except Exception as e:  # noqa: BLE001
        logger.warning("update check failed: %s", e)
    return None


def check() -> dict:
    cur = current_version()
    rel = latest_release()
    out = {"enabled": frozen(), "current": cur,
           "available": False, "latest": None, "url": None}
    if rel and rel["tag"]:
        cur_ver, new_ver = _semver(cur), _semver(rel["tag"])
        newer = (cur_ver and new_ver and new_ver > cur_ver) or \
                (not cur_ver and rel["tag"] != cur)
        out.update(available=bool(frozen() and newer),
                   latest=rel["tag"], url=rel["url"])
    return out


_UPDATER_BAT = r"""@echo off
rem Swap in the new StudyThing build, then restart.
title StudyThing updater
ping -n 4 127.0.0.1 >nul
robocopy "%~dp0update-staging" "%~dp0" /E /NFL /NDL /NJH /NJS >nul
if exist "%~dp0update-staging" rmdir /S /Q "%~dp0update-staging"
start "" "%~dp0StudyThing.exe"
exit
"""


def install(url: str) -> dict:
    """Download release zip -> staging -> write updater bat -> spawn -> exit."""
    if not frozen():
        raise RuntimeError("self-update only works in the installed app")
    exe_dir = _exe_dir()
    staging = exe_dir / "update-staging"
    if staging.exists():
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    zpath = staging.parent / "update.zip"
    logger.warning("downloading update from %s", url)
    with requests.get(url, stream=True, timeout=3600, allow_redirects=True) as r:
        r.raise_for_status()
        with zpath.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(staging)
    zpath.unlink(missing_ok=True)
    exe = next(staging.rglob("StudyThing.exe"), None)
    if exe is None:
        raise RuntimeError("downloaded update has no StudyThing.exe")
    # flatten if the zip wrapped everything in a subfolder
    if exe.parent != staging:
        import shutil
        for item in exe.parent.iterdir():
            shutil.move(str(item), str(staging / item.name))
        import shutil as _s
        _s = exe.parent
        if _s != staging and not any(_s.iterdir()):
            _s.rmdir()
    (staging / "apply-update.bat").write_text(_UPDATER_BAT, encoding="ascii")
    subprocess.Popen(["cmd", "/c", str(staging / "apply-update.bat")],
                     cwd=str(exe_dir), creationflags=0x00000008)  # DETACHED
    logger.warning("update staged; exiting for swap")
    os._exit(0)  # the bat restarts us with the new build
