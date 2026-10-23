"""
vlc_player.py — JARVIS plugin

"Jarvis, play [video name] in VLC" — searches the user's common video
folders (Videos, Downloads, Desktop, Documents) for a file matching the
name, picks the best match, and opens it in VLC media player.

For local video files only. YouTube/online videos are handled by the
existing youtube_video tool, not this one.

Drop this file into /plugins/ — no other file needs to change.
"""

import difflib
import os
import platform
import shutil
import subprocess
from pathlib import Path

PLUGIN = {
    "name": "play_video_vlc",
    "description": (
        "Searches the user's computer for a LOCAL video file by name and plays "
        "it in VLC media player. Use when the user says things like 'play "
        "<video> in vlc', 'open <video> with vlc', 'play the video called "
        "X', 'find and play <video>'. Do NOT use this for YouTube or other "
        "online/streaming video — use the youtube_video tool for that instead. "
        "This tool only searches local folders (Videos, Downloads, Desktop, "
        "Documents, home directory)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "The video name or keywords the user said, e.g. "
                                "'the wedding video' or 'project demo'. Doesn't "
                                "need to be exact — this does fuzzy matching "
                                "against real filenames.",
            },
            "search_path": {
                "type": "STRING",
                "description": "Optional. A specific folder to search instead of "
                                "the default common video locations, if the user "
                                "names one (e.g. 'in my Downloads folder').",
            },
        },
        "required": ["query"],
    },
}

_OS = platform.system()
_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
               ".webm", ".m4v", ".mpg", ".mpeg", ".3gp"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", "$recycle.bin",
              "appdata", "library", ".cache", ".local", "windows", "program files",
              "program files (x86)"}
_MAX_DEPTH = 5
_MAX_FILES_SCANNED = 20000   # safety cap so a huge home dir can't hang the assistant


def _xdg_or_default(env_var: str, folder: str) -> Path:
    if _OS == "Linux":
        xdg = os.environ.get(env_var, "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / folder


def _default_search_dirs() -> list[Path]:
    dirs = [
        _xdg_or_default("XDG_VIDEOS_DIR", "Videos"),
        _xdg_or_default("XDG_DOWNLOAD_DIR", "Downloads"),
        _xdg_or_default("XDG_DESKTOP_DIR", "Desktop"),
        _xdg_or_default("XDG_DOCUMENTS_DIR", "Documents"),
    ]
    if _OS == "Darwin":
        movies = Path.home() / "Movies"
        if movies.exists():
            dirs.append(movies)
    return [d for d in dirs if d.exists()]


def _is_safe(target: Path) -> bool:
    """Never search or play from outside the user's home directory."""
    try:
        home = Path.home().resolve()
        resolved = target.resolve()
        return resolved == home or resolved.is_relative_to(home)
    except Exception:
        return False


def _walk_videos(root: Path, max_depth: int = _MAX_DEPTH):
    """Yields video file Paths under root, skipping noisy/system dirs, depth-bounded."""
    root_depth = len(root.resolve().parts)
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).resolve().parts) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                        if not d.startswith(".") and d.lower() not in _SKIP_DIRS]
        for fname in filenames:
            scanned += 1
            if scanned > _MAX_FILES_SCANNED:
                return
            if Path(fname).suffix.lower() in _VIDEO_EXTS:
                yield Path(dirpath) / fname


def _score(query_norm: str, filename: str) -> float:
    stem = Path(filename).stem.lower().replace("_", " ").replace(".", " ").replace("-", " ")
    if query_norm in stem:
        # substring match — strong signal, weighted by how much of the name it covers
        return 0.75 + 0.25 * (len(query_norm) / max(len(stem), 1))
    return difflib.SequenceMatcher(None, query_norm, stem).ratio()


def _find_best_match(query: str, search_dirs: list[Path]):
    """Returns (best_path, score, runner_up_count) or (None, 0, 0) if nothing found."""
    query_norm = query.strip().lower().replace("_", " ").replace(".", " ").replace("-", " ")
    if not query_norm:
        return None, 0.0, 0

    scored = []
    for d in search_dirs:
        if not _is_safe(d):
            continue
        for path in _walk_videos(d):
            scored.append((_score(query_norm, path.name), path))

    if not scored:
        return None, 0.0, 0

    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_path = scored[0]
    close_matches = sum(1 for s, _ in scored if s >= best_score - 0.1 and s >= 0.3) - 1
    return best_path, best_score, close_matches


def _find_vlc_executable():
    """Returns a path/command usable to launch VLC, or None if not found."""
    candidates = []
    if _OS == "Windows":
        which = shutil.which("vlc") or shutil.which("vlc.exe")
        if which:
            candidates.append(which)
        candidates += [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ]
    elif _OS == "Darwin":
        which = shutil.which("vlc")
        if which:
            candidates.append(which)
        candidates.append("/Applications/VLC.app/Contents/MacOS/VLC")
    else:  # Linux
        which = shutil.which("vlc")
        if which:
            candidates.append(which)
        candidates += ["/usr/bin/vlc", "/snap/bin/vlc", "/usr/local/bin/vlc"]

    for c in candidates:
        if c and (shutil.which(c) or Path(c).is_file()):
            return c
    return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    query = (parameters.get("query") or "").strip()
    search_path = (parameters.get("search_path") or "").strip()

    if not query:
        return "Sir, I need to know which video to look for."

    try:
        if search_path:
            root = Path(search_path).expanduser()
            if not root.is_dir() or not _is_safe(root):
                return f"Sir, I can't search '{search_path}' — it's not a valid or accessible folder."
            search_dirs = [root]
        else:
            search_dirs = _default_search_dirs()
            if not search_dirs:
                return "Sir, I couldn't find any of your usual video folders to search."

        best_path, score, close_matches = _find_best_match(query, search_dirs)

        if best_path is None:
            return f"Sir, I couldn't find any video matching '{query}' in your Videos, Downloads, Desktop, or Documents folders."

        if score < 0.35:
            return (f"Sir, the closest thing I found was '{best_path.name}', but that's not a "
                     "confident match. Try giving me more of the exact file name.")

        vlc_exe = _find_vlc_executable()
        if vlc_exe is None:
            return ("Sir, I found the video but couldn't locate VLC on this machine. "
                    "Make sure VLC is installed and try again.")

        try:
            subprocess.Popen([vlc_exe, str(best_path)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return f"Sir, I found '{best_path.name}' but VLC failed to launch: {e}"

        result_text = f"Playing '{best_path.name}' in VLC, sir."
        if close_matches > 0:
            result_text += f" ({close_matches} other similarly-named video(s) found — say the exact name if this wasn't the one.)"

    except Exception as e:
        return f"Sir, play_video_vlc failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
