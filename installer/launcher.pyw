"""MARK LV production launcher.

Start Menu / Desktop shortcuts run:  runtime\\pythonw.exe launcher.pyw

It does NOT replace main.py (developers keep running `python main.py`). It only
wraps it with the things a packaged app needs and the source tree doesn't have:

  * a log file in %LOCALAPPDATA%\\MARK-LV\\logs  (secrets are redacted)
  * a friendly "Something went wrong" dialog if the app dies, with
    Restart / Open logs / Close
  * a Windows AppUserModelID so the taskbar shows MARK LV, not "Python"

Set MARKLV_LOG_DIR to override the log folder (used by the tests).
"""
import ctypes
import datetime
import os
import re
import runpy
import subprocess
import sys
import threading
import traceback
from pathlib import Path

APP_NAME = "MARK-LV"
APP_DIR = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"


def log_dir() -> Path:
    override = os.environ.get("MARKLV_LOG_DIR")
    if override:
        base = Path(override)
    else:
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        base = Path(root) / APP_NAME / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ── secret redaction ─────────────────────────────────────────────────────────
_SECRETS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),                        # Google / Gemini API key
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"),               # Telegram bot token
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                         # OpenAI-style key
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\"?\s*[:=]\s*\"?)([^\s\"',}]{8,})"),
]


# Exact values of every credential saved in config/api_keys.json. Patterns alone miss key formats we
# have not seen (Google has more than one), so the real values are redacted wherever they appear.
_literals: list[str] = []
_literals_mtime = None
_literals_checked = 0.0
_SECRET_NAME = re.compile(r"(?i)key|token|secret|pass|credential|bearer")


def _collect(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if _SECRET_NAME.search(str(k)) and len(v) >= 8:
                    out.append(v)
            else:
                _collect(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, out)


def _refresh_literals():
    """Re-read the config at most every 5 s, and only when the file changed."""
    global _literals, _literals_mtime, _literals_checked
    import json
    import time
    now = time.monotonic()
    if now - _literals_checked < 5:
        return
    _literals_checked = now
    cfg = APP_DIR / "config" / "api_keys.json"
    try:
        mt = cfg.stat().st_mtime
        if mt == _literals_mtime:
            return
        found: list[str] = []
        _collect(json.loads(cfg.read_text(encoding="utf-8")), found)
        _literals = sorted(set(found), key=len, reverse=True)
        _literals_mtime = mt
    except (OSError, ValueError):
        pass


def redact(text: str) -> str:
    _refresh_literals()
    for lit in _literals:
        if lit in text:
            text = text.replace(lit, "[REDACTED]")
    for rx in _SECRETS[:3]:
        text = rx.sub("[REDACTED]", text)
    return _SECRETS[3].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


class _LogStream:
    """File-like object for stdout/stderr (pythonw has none)."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, fh):
        self._fh = fh
        self._lock = threading.Lock()

    def write(self, s):
        if not s:
            return 0
        with self._lock:
            try:
                self._fh.write(redact(str(s)))
                self._fh.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False

    def reconfigure(self, **_kw):  # main.py calls this on its streams
        pass


def open_log() -> Path:
    d = log_dir()
    path = d / "mark-lv.log"
    try:  # keep one previous log, rotate at 2 MB
        if path.exists() and path.stat().st_size > 2_000_000:
            old = d / "mark-lv.previous.log"
            old.unlink(missing_ok=True)
            path.rename(old)
    except OSError:
        pass
    fh = open(path, "a", encoding="utf-8", errors="replace")
    fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} — launch "
             f"(Python {sys.version.split()[0]}) =====\n")
    fh.flush()
    # Always capture; if a real console exists (python.exe / dev use) keep it too.
    sys.stdout = _LogStream(fh)
    sys.stderr = _LogStream(fh)
    return path


def read_version() -> str:
    try:
        return (APP_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


def _hook(exc_type, exc, tb):
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return
    traceback.print_exception(exc_type, exc, tb)


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    print(f"[thread {getattr(args.thread, 'name', '?')}] unhandled exception:", file=sys.stderr)
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


def crash_dialog(logfile: Path) -> str:
    """Return 'restart', 'logs' or 'close'. Windows only; elsewhere just 'close'."""
    if not IS_WIN:
        return "close"
    MB_YESNOCANCEL, MB_ICONERROR, MB_TOPMOST = 0x3, 0x10, 0x40000
    text = ("Something went wrong.\n\n"
            "An error report has been saved to your application logs.\n\n"
            "Yes  -  Restart MARK LV\nNo  -  Open the logs folder\nCancel  -  Close")
    try:
        r = ctypes.windll.user32.MessageBoxW(0, text, "MARK LV", MB_YESNOCANCEL | MB_ICONERROR | MB_TOPMOST)
    except Exception:
        return "close"
    return {6: "restart", 7: "logs"}.get(r, "close")


def _recovery_cli() -> Path:
    return APP_DIR / "core" / "update_recovery_cli.py"


def _recovery_install_root() -> Path:
    if sys.platform == "darwin":
        for parent in APP_DIR.parents:
            if parent.suffix == ".app":
                return parent
    return APP_DIR


def _start_rollback_worker(transaction_id: str, backup_dir: str) -> bool:
    backup = Path(backup_dir).resolve()
    if sys.platform == "darwin":
        bundled_root = backup / "Contents" / "Resources" / "MARK-LV"
        worker = bundled_root / "core" / "update_recovery_worker.py"
        python = bundled_root / "runtime" / "bin" / "python3.12"
    else:
        worker = backup / "core" / "update_recovery_worker.py"
        if os.name == "nt":
            python = backup / "runtime" / "python.exe"
        else:
            python = backup / "runtime" / "bin" / "python3.12"
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs = {"creationflags": flags, "close_fds": True}
    else:
        kwargs = {"start_new_session": True, "close_fds": True}
    if not python.is_file() or not worker.is_file():
        print("Update recovery helper is missing; manual recovery is required.", file=sys.stderr)
        return False
    try:
        subprocess.Popen(
            [str(python), str(worker), transaction_id, str(os.getpid())],
            cwd=str(backup), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs,
        )
        return True
    except Exception:
        traceback.print_exc()
        return False


def _begin_update_health_check():
    cli = _recovery_cli()
    if not cli.is_file():
        return None, None, None
    try:
        result = subprocess.run(
            [sys.executable, str(cli), "--begin-startup", str(APP_DIR), "--pid", str(os.getpid())],
            cwd=str(APP_DIR), capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("Update recovery check could not run: " + result.stderr.strip(), file=sys.stderr)
            return None, None, None
        import json
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        status = payload.get("status")
        if status == "already_running":
            return "already_running", None, None
        if status == "needs_rollback":
            _start_rollback_worker(str(payload["transaction_id"]), str(payload["backup_dir"]))
            return "rollback_scheduled", None, None
        if status != "health_check_started":
            return None, None, None
        transaction_id = str(payload["transaction_id"])
        backup_dir = str(payload["backup_dir"])

        def confirm():
            try:
                subprocess.run(
                    [sys.executable, str(cli), "--confirm-id", transaction_id],
                    cwd=str(APP_DIR), capture_output=True, text=True, timeout=30, check=True,
                )
                print("Update startup health window passed; recovery backup committed.")
            except Exception as exc:
                print(f"Could not confirm update recovery transaction: {exc}", file=sys.stderr)

        timer = threading.Timer(90.0, confirm)
        timer.daemon = True
        timer.start()
        return transaction_id, timer, backup_dir
    except Exception:
        traceback.print_exc()
        return None, None, None


def _finish_update_health_check(transaction_id, timer, backup_dir, *, healthy: bool):
    if timer:
        timer.cancel()
    if not transaction_id:
        return
    cli = _recovery_cli()
    if healthy:
        try:
            subprocess.run(
                [sys.executable, str(cli), "--confirm-id", transaction_id],
                cwd=str(APP_DIR), capture_output=True, text=True, timeout=30, check=True,
            )
            print("Update completed its startup health check.")
        except Exception as exc:
            print(f"Update confirmation failed: {exc}", file=sys.stderr)
    else:
        if backup_dir:
            _start_rollback_worker(transaction_id, str(backup_dir))


def main() -> int:
    logfile = open_log()
    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    print(f"MARK LV {read_version()} starting from {APP_DIR}")

    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MarkLV.Jarvis")
        except Exception:
            pass

    os.chdir(APP_DIR)
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    sys.argv = [str(APP_DIR / "main.py")]

    transaction_id, health_timer, backup_dir = _begin_update_health_check()
    if transaction_id == "already_running":
        return 0
    if transaction_id == "rollback_scheduled":
        return 1

    try:
        runpy.run_path(str(APP_DIR / "main.py"), run_name="__main__")
        _finish_update_health_check(transaction_id, health_timer, backup_dir, healthy=True)
        return 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
        _finish_update_health_check(transaction_id, health_timer, backup_dir, healthy=(code == 0))
        return code
    except BaseException:
        _finish_update_health_check(transaction_id, health_timer, backup_dir, healthy=False)
        traceback.print_exc()
        choice = crash_dialog(logfile)
        if choice == "restart":
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])
        elif choice == "logs" and IS_WIN:
            os.startfile(str(logfile.parent))  # noqa: S606 - opens a folder in Explorer
        return 1


if __name__ == "__main__":
    sys.exit(main())
