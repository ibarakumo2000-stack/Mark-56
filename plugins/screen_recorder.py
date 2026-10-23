"""
screen_recorder — JARVIS plugin: record the screen + audio, with a floating control bar.

Drop this file into  <jarvis>/plugins/  — nothing else needs to change.

Voice:   "record my screen" / "pause the recording" / "resume" / "restart the recording"
         / "stop recording" / "open my recordings"
Output:  <Videos>/JARVIS Recordings/Screen Recording YYYY-MM-DD HH-MM-SS.mp4

Install (once):
    pip install mss imageio-ffmpeg soundcard
      mss             screen capture                       (required)
      imageio-ffmpeg  bundled ffmpeg for H.264 + AAC       (required, unless ffmpeg is on PATH)
      soundcard       system-audio ("what you hear")       (optional — without it, mic only)
    Microphone capture uses sounddevice, which JARVIS already depends on.

How it works
    * Video: mss grabs frames on a fixed 30 fps timeline and pipes them to ffmpeg (H.264).
      The mouse pointer is drawn onto each frame (mss does not capture it).
    * Audio: system sound (WASAPI loopback) and the microphone are written to separate WAVs on
      their own threads, then mixed and muxed into the MP4 when you stop.
    * Pause freezes the recording clock for video AND audio, so nothing drifts out of sync and the
      paused stretch is simply cut out of the file.
    * Restart throws away the current take and starts a fresh one.
    * The control bar is a small always-on-top PyQt6 window. On Windows 10 (2004+) it is excluded
      from screen capture, so it never appears in your recording.
"""
from __future__ import annotations

import atexit
import ctypes
import importlib
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from datetime import datetime
from pathlib import Path

# ── Plugin declaration ────────────────────────────────────────────────────────

PLUGIN = {
    "name": "screen_recorder",
    "description": (
        "Records the user's screen as a video WITH audio (system sound and/or microphone) and saves "
        "it as an MP4 in the Videos folder. While recording, a small floating control bar with "
        "Pause / Resume / Stop / Restart / Start buttons is shown on screen. "
        "Use for: 'record my screen', 'start screen recording', 'stop recording', 'pause the "
        "recording', 'resume recording', 'restart the recording', 'is the recording running', "
        "'open my recordings folder'. "
        "action = start | stop | pause | resume | restart | status | open_folder. "
        "audio (only for start/restart) = both (default: system sound + microphone) | system | mic "
        "| none. "
        "Do NOT use this to look at, read or describe what is currently on the screen — use "
        "screen_process for that. This tool produces a video file."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "start | stop | pause | resume | restart | status | open_folder",
            },
            "audio": {
                "type": "STRING",
                "description": "Which audio to record: both (default) | system | mic | none",
            },
        },
        "required": ["action"],
    },
}

# ── Settings (edit freely) ────────────────────────────────────────────────────

FPS            = 30          # capture / output frame rate
VIDEO_CRF      = 23          # x264 quality: lower = better + bigger (18 near-lossless … 28 small)
VIDEO_PRESET   = "veryfast"  # x264 speed/size trade-off; "ultrafast" if the CPU struggles
FOLDER_NAME    = "JARVIS Recordings"   # created inside the user's Videos folder
MAX_MINUTES    = 180         # safety net: a take is stopped and saved automatically at this length
MAX_CAPTURE_W  = 2560        # wider screens are captured at half size to keep the pipe real-time

# ── Internals ─────────────────────────────────────────────────────────────────

_IS_WIN = platform.system() == "Windows"
_NOWIN = {"creationflags": subprocess.CREATE_NO_WINDOW} if _IS_WIN else {}

_IDLE, _STARTING, _REC, _PAUSED, _SAVING = "idle", "starting", "recording", "paused", "saving"


class _RecError(Exception):
    """A problem worth telling the user about. Message is a full, speakable sentence."""


# ---- small helpers ----------------------------------------------------------

def _clock(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _spoken(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s or not parts:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts)


def _videos_dir() -> Path:
    try:
        from PyQt6.QtCore import QStandardPaths
        p = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
        if p:
            return Path(p)
    except Exception:
        pass
    return Path.home() / "Videos"


def _out_dir() -> Path:
    d = _videos_dir() / FOLDER_NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise _RecError(f"I can't create the recordings folder at {d}: {e}")
    return d


def _com_init() -> bool:
    """Soundcard talks to WASAPI through COM; every thread that uses it must join the MTA."""
    if not _IS_WIN:
        return False
    try:
        return ctypes.windll.ole32.CoInitializeEx(None, 0) in (0, 1)   # S_OK / S_FALSE
    except Exception:
        return False


def _com_uninit(inited: bool) -> None:
    if inited:
        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass


def _to_pcm16(np, data):
    return (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


# ---- dependencies -----------------------------------------------------------

class _Deps:
    np = None
    mss = None
    ffmpeg = ""
    encoder: list = []


_deps_cache: _Deps | None = None


def _find_ffmpeg() -> str:
    try:
        exe = importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg") or ""


def _pick_encoder(ffmpeg: str) -> list:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                             text=True, timeout=20, **_NOWIN).stdout
    except Exception:
        out = ""
    if " libx264 " in out:
        return ["-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF)]
    return ["-c:v", "mpeg4", "-q:v", "4"]          # an ffmpeg build without x264


def _load_deps() -> _Deps:
    global _deps_cache
    if _deps_cache is not None:
        return _deps_cache
    d = _Deps()
    missing = []
    try:
        d.np = importlib.import_module("numpy")
    except Exception:
        missing.append("numpy")
    try:
        d.mss = importlib.import_module("mss")
    except Exception:
        missing.append("mss")
    d.ffmpeg = _find_ffmpeg()
    if not d.ffmpeg:
        missing.append("imageio-ffmpeg")
    if missing:
        cmd = "pip install " + " ".join(missing)
        RECORDER.log(f"SYS: Screen recorder needs: {cmd}")
        raise _RecError("I'm missing a package for screen recording. "
                        f"I've put the install command in the log: {cmd}.")
    d.encoder = _pick_encoder(d.ffmpeg)
    _deps_cache = d
    return d


# ---- mouse pointer overlay --------------------------------------------------

_ARROW = [
    "B..........",
    "BB.........",
    "BWB........",
    "BWWB.......",
    "BWWWB......",
    "BWWWWB.....",
    "BWWWWWB....",
    "BWWWWWWB...",
    "BWWWWWWWB..",
    "BWWWWWWWWB.",
    "BWWWWWBBBBB",
    "BWWBWWB....",
    "BWB.BWWB...",
    "BB..BWWB...",
    "B....BWWB..",
    ".....BWWB..",
    "......BB...",
]


def _cursor_sprite(np, scale: int):
    pal = {"B": (0, 0, 0, 255), "W": (255, 255, 255, 255), ".": (0, 0, 0, 0)}
    arr = np.zeros((len(_ARROW), len(_ARROW[0]), 4), dtype=np.uint8)
    for y, row in enumerate(_ARROW):
        for x, ch in enumerate(row):
            arr[y, x] = pal[ch]
    if scale > 1:
        arr = arr.repeat(scale, axis=0).repeat(scale, axis=1)
    return arr


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _cursor_pos():
    if not _IS_WIN:
        return None
    try:
        pt = _POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
    except Exception:
        pass
    return None


def _blit(frame, sprite, x: int, y: int) -> None:
    fh, fw = frame.shape[:2]
    sh, sw = sprite.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + sw, fw), min(y + sh, fh)
    if x1 <= x0 or y1 <= y0:
        return
    s = sprite[y0 - y:y1 - y, x0 - x:x1 - x]
    m = s[..., 3] > 0
    frame[y0:y1, x0:x1][m] = s[m]


# ── One recording ("take") ────────────────────────────────────────────────────

class _Take:
    def __init__(self, audio_mode: str, owner: "_Recorder"):
        self.audio_mode = audio_mode
        self.owner = owner
        self.notes: list[str] = []

        self.tmp: Path | None = None
        self.proc: subprocess.Popen | None = None
        self._ff_log = None

        self.stop_evt = threading.Event()
        self.running = threading.Event()        # set = clock running, audio is being kept
        self._clock_lock = threading.Lock()
        self._accum = 0.0
        self._t_resume: float | None = None

        self.frames = 0
        self._limit_fired = False
        self._failed = False
        self._video_thread: threading.Thread | None = None

        self._mic_stream = None
        self._mic_thread: threading.Thread | None = None
        self._mic_q: queue.Queue | None = None
        self._mic_rate = 0
        self._sys_thread: threading.Thread | None = None
        self._sys_ready = threading.Event()
        self.has_mic = False
        self.has_sys = False
        self.sys_error = ""

    # -- clock (only counts time while recording; pausing freezes it) --------
    def elapsed(self) -> float:
        with self._clock_lock:
            t = self._accum
            if self._t_resume is not None:
                t += time.monotonic() - self._t_resume
            return t

    def pause_clock(self) -> None:
        with self._clock_lock:
            if self._t_resume is not None:
                self._accum += time.monotonic() - self._t_resume
                self._t_resume = None
        self.running.clear()

    def resume_clock(self) -> None:
        with self._clock_lock:
            if self._t_resume is None:
                self._t_resume = time.monotonic()
        self.running.set()

    # -- setup ---------------------------------------------------------------
    def open(self) -> None:
        d = _load_deps()
        self.d = d
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis_rec_"))

        try:
            with d.mss.mss() as sct:
                mons = sct.monitors
                mon = dict(mons[1] if len(mons) > 1 else mons[0])   # [1] = primary display
        except Exception as e:
            raise _RecError(f"I couldn't access the screen: {e}")

        w, h = int(mon["width"]), int(mon["height"])
        self.dec = 2 if w > MAX_CAPTURE_W else 1
        align = 2 * self.dec                     # H.264 4:2:0 needs even output dimensions
        w -= w % align
        h -= h % align
        if w < 16 or h < 16:
            raise _RecError("The screen size looks wrong, so I can't record it.")
        self.region = {"left": int(mon["left"]), "top": int(mon["top"]), "width": w, "height": h}
        self.out_w, self.out_h = w // self.dec, h // self.dec
        self.sprite = _cursor_sprite(d.np, max(1, round(h / 1080)))

        self.video_path = self.tmp / "video.mp4"
        self.mic_path = self.tmp / "mic.wav"
        self.sys_path = self.tmp / "system.wav"

        cmd = [
            d.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr0",
            "-s", f"{self.out_w}x{self.out_h}", "-framerate", str(FPS), "-i", "-",
            "-an",
            "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            *d.encoder,
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-r", str(FPS), str(self.video_path),
        ]
        self._ff_log = open(self.tmp / "ffmpeg.log", "wb")
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=self._ff_log, **_NOWIN)
        except Exception as e:
            raise _RecError(f"I couldn't start the video encoder: {e}")

        self._open_audio()

    def _open_audio(self) -> None:
        mode = self.audio_mode
        want_sys = mode in ("both", "system")
        want_mic = mode in ("both", "mic")

        if want_sys:
            try:
                importlib.import_module("soundcard")
            except Exception:
                self.notes.append("System audio needs the soundcard package, so it is off.")
                RECORDER.log("SYS: For system audio run: pip install soundcard")
            else:
                self._sys_thread = threading.Thread(target=self._sys_loop, name="rec-sys-audio",
                                                    daemon=True)
                self._sys_thread.start()
                self._sys_ready.wait(5.0)
                if not self.has_sys:
                    self.notes.append("System audio isn't available on this device, so it is off.")
                    if self.sys_error:
                        RECORDER.log(f"SYS: System-audio capture failed: {self.sys_error}")
        if want_mic:
            try:
                self._open_mic()
            except Exception as e:
                self.notes.append("The microphone couldn't be opened, so it is off.")
                RECORDER.log(f"SYS: Microphone capture failed: {e}")

    def _open_mic(self) -> None:
        sd = importlib.import_module("sounddevice")
        dev = None
        try:                                   # honour the mic chosen in JARVIS settings
            from memory.config_manager import get_input_device
            from core import audio_devices
            dev = audio_devices.resolve(get_input_device(), "input")
        except Exception:
            dev = None

        last: Exception | None = None
        for cand in ([dev, None] if dev is not None else [None]):
            try:
                info = sd.query_devices(cand, "input")
                rate = int(info["default_samplerate"])
                q: queue.Queue = queue.Queue()

                def cb(indata, frames, t, status, _q=q):
                    if self.running.is_set():
                        _q.put(indata.copy())

                stream = sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                                        device=cand, callback=cb)
                stream.start()
                self._mic_stream, self._mic_q, self._mic_rate = stream, q, rate
                self._mic_thread = threading.Thread(target=self._mic_writer, name="rec-mic",
                                                    daemon=True)
                self._mic_thread.start()
                self.has_mic = True
                return
            except Exception as e:
                last = e
        raise last or RuntimeError("no input device")

    def begin(self) -> None:
        self._video_thread = threading.Thread(target=self._video_loop, name="rec-video", daemon=True)
        self._video_thread.start()
        self.resume_clock()
        if self.audio_mode == "none":
            self.notes.append("No audio.")

    # -- worker threads ------------------------------------------------------
    def _video_loop(self) -> None:
        np = self.d.np
        w, h = self.region["width"], self.region["height"]
        last = None
        fails = 0
        try:
            with self.d.mss.mss() as sct:                    # mss objects are per-thread
                while not self.stop_evt.is_set():
                    if not self.running.wait(0.1):
                        continue                              # paused
                    active = self.elapsed()
                    if active >= MAX_MINUTES * 60 and not self._limit_fired:
                        self._limit_fired = True
                        self.owner.on_limit(self)
                    due = int(active * FPS) - self.frames
                    if due <= 0:
                        time.sleep(max(0.002, (self.frames + 1) / FPS - active))
                        continue

                    try:
                        shot = sct.grab(self.region)
                        if (shot.width, shot.height) != (w, h):
                            raise RuntimeError("the screen resolution changed during recording")
                        buf = np.frombuffer(shot.raw, dtype=np.uint8)
                        if not buf.flags.writeable:
                            buf = buf.copy()
                        frame = buf.reshape(h, w, 4)
                        pos = _cursor_pos()
                        if pos is not None:
                            _blit(frame, self.sprite, pos[0] - self.region["left"],
                                  pos[1] - self.region["top"])
                        if self.dec > 1:
                            frame = np.ascontiguousarray(frame[::self.dec, ::self.dec])
                        last = frame.data.cast("B")
                        fails = 0
                    except RuntimeError:
                        raise
                    except Exception:
                        # Secure desktop (UAC prompt, lock screen) can't be grabbed: hold the
                        # last frame instead of killing the recording.
                        fails += 1
                        if last is None or fails > FPS * 15:
                            raise
                        time.sleep(0.05)

                    stdin = self.proc.stdin
                    for _ in range(due):
                        stdin.write(last)
                    self.frames += due
        except Exception as e:
            if not self.stop_evt.is_set() and not self._failed:
                self._failed = True
                self.owner.on_failure(self, f"the video capture stopped: {e}")

    def _mic_writer(self) -> None:
        try:
            with wave.open(str(self.mic_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self._mic_rate)
                q = self._mic_q
                while True:
                    try:
                        wf.writeframes(q.get(timeout=0.1).tobytes())
                    except queue.Empty:
                        if self.stop_evt.is_set():
                            break
        except Exception as e:
            RECORDER.log(f"SYS: Microphone writer stopped: {e}")

    def _sys_loop(self) -> None:
        np = self.d.np
        com = _com_init()
        wf = None
        try:
            sc = importlib.import_module("soundcard")
            spk = sc.default_speaker()
            loop_mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            rate, ch, block = 48000, 2, 4800                  # 100 ms blocks
            wf = wave.open(str(self.sys_path), "wb")
            wf.setnchannels(ch)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            with loop_mic.recorder(samplerate=rate, channels=ch, blocksize=block) as rec:
                self.has_sys = True
                self._sys_ready.set()
                while not self.stop_evt.is_set():
                    data = rec.record(numframes=block)        # always drain, even while paused
                    if self.running.is_set():
                        wf.writeframes(_to_pcm16(np, data))
        except Exception as e:
            self.sys_error = str(e)
        finally:
            if wf is not None:
                try:
                    wf.close()
                except Exception:
                    pass
            self._sys_ready.set()
            _com_uninit(com)

    # -- finishing -----------------------------------------------------------
    def _stop_workers(self) -> int:
        """Stop every thread and the encoder; returns ffmpeg's exit code."""
        self.pause_clock()
        self.stop_evt.set()
        if self._video_thread:
            self._video_thread.join(15)
        rc = -1
        if self.proc:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                rc = self.proc.wait(timeout=120)
            except Exception:
                self.proc.kill()
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
        for t in (self._mic_thread, self._sys_thread):
            if t:
                t.join(10)
        if self._ff_log:
            try:
                self._ff_log.close()
            except Exception:
                pass
        return rc

    def _log_tail(self) -> str:
        try:
            txt = (self.tmp / "ffmpeg.log").read_text(errors="replace").strip().splitlines()
            return " | ".join(txt[-3:])
        except Exception:
            return ""

    @staticmethod
    def _has_audio(p: Path) -> bool:
        try:
            if not p.exists():
                return False
            with wave.open(str(p), "rb") as wf:
                return wf.getnframes() > wf.getframerate() // 20      # > 50 ms
        except Exception:
            return False

    def finish(self, dest_dir: Path) -> tuple[Path, float]:
        duration = self.elapsed()
        rc = self._stop_workers()
        if self.frames == 0:
            raise _RecError("That recording was too short to save.")
        if rc != 0 or not self.video_path.exists() or self.video_path.stat().st_size == 0:
            raise _RecError(f"The video encoder failed. {self._log_tail()}")

        stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        dest = dest_dir / f"Screen Recording {stamp}.mp4"
        n = 2
        while dest.exists():
            dest = dest_dir / f"Screen Recording {stamp} ({n}).mp4"
            n += 1

        audio = []
        if self.has_mic and self._has_audio(self.mic_path):
            audio.append(self.mic_path)
        if self.has_sys and self._has_audio(self.sys_path):
            audio.append(self.sys_path)

        if not audio:
            shutil.copy2(self.video_path, dest)
        else:
            if not self._mux(audio, dest):
                RECORDER.log("SYS: Audio mixing failed — saved the video without sound. "
                             + self._mux_err)
                shutil.copy2(self.video_path, dest)
        self.cleanup()
        return dest, duration

    _mux_err = ""

    def _mux(self, audio: list[Path], dest: Path) -> bool:
        cmd = [self.d.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
               "-i", str(self.video_path)]
        for a in audio:
            cmd += ["-i", str(a)]
        norm = "aresample=48000,aformat=channel_layouts=stereo"
        if len(audio) == 1:
            graph = f"[1:a]{norm},apad[a]"
        else:
            graph = (f"[1:a]{norm}[m];[2:a]{norm}[s];"
                     "[m][s]amix=inputs=2:duration=longest:dropout_transition=0,"
                     "volume=2,alimiter=limit=0.95,apad[a]")
        cmd += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                "-shortest", "-movflags", "+faststart", str(dest)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, **_NOWIN)
        except Exception as e:
            self._mux_err = str(e)
            return False
        if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            self._mux_err = (r.stderr or "").strip()[-300:]
            try:
                dest.unlink()
            except Exception:
                pass
            return False
        return True

    def abort(self) -> None:
        """Throw the take away (restart, failure, shutdown without saving)."""
        try:
            self.stop_evt.set()
            self.pause_clock()
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
            self._stop_workers()
        except Exception:
            pass
        self.cleanup()

    def cleanup(self) -> None:
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None


# ── Controller (one per process) ──────────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self._lock = threading.RLock()
        self.state = _IDLE
        self.take: _Take | None = None
        self.player = None
        self.audio_mode = "both"
        self.result: tuple[Path, float] | None = None     # last saved (path, seconds)
        self.error = ""

    # -- plumbing ------------------------------------------------------------
    def log(self, text: str) -> None:
        try:
            if self.player:
                self.player.write_log(text)
            else:
                print(f"[ScreenRecorder] {text}")
        except Exception:
            pass

    def say(self, instruction: str) -> None:
        """Speak without a voice command (button presses, auto-stop)."""
        try:
            fn = getattr(self.player, "request_say", None)
            if callable(fn):
                fn(instruction)
        except Exception:
            pass

    def _notify(self) -> None:
        _ui_call(_bar_refresh)

    def snapshot(self):
        with self._lock:
            t = self.take
            el = t.elapsed() if (t and self.state in (_REC, _PAUSED)) else 0.0
            if self.state == _IDLE:
                if self.error:
                    info = self.error
                elif self.result:
                    info = f"Saved {_clock(self.result[1])}"
                else:
                    info = ""
            else:
                info = ""
            return self.state, el, info

    def busy_text(self) -> str:
        st, el, _ = self.snapshot()
        if st in (_REC, _PAUSED):
            return (f"I'm already recording, sir — {_spoken(el)} so far"
                    + (" (paused)." if st == _PAUSED else "."))
        return "One moment, sir — the recorder is busy."

    # -- commands (all thread-safe) -------------------------------------------
    def start(self, audio: str | None = None) -> str:
        with self._lock:
            if self.state != _IDLE:
                return self.busy_text()
            self.state = _STARTING
            self.error = ""
            self.result = None
            if audio:
                self.audio_mode = audio
        self._notify()
        return self._launch()

    def _launch(self) -> str:
        take = _Take(self.audio_mode, self)
        try:
            take.open()
            take.begin()
        except Exception as e:
            take.abort()
            with self._lock:
                self.state = _IDLE
                self.error = str(e)[:90]
            self._notify()
            raise
        with self._lock:
            self.take = take
            self.state = _REC
        self._notify()
        extra = (" " + " ".join(take.notes)) if take.notes else ""
        if not take.notes:
            parts = [n for n, ok in (("system sound", take.has_sys), ("microphone", take.has_mic)) if ok]
            extra = f" Recording {' and '.join(parts)}." if parts else ""
        bar = "" if _ui_available() else " The control bar isn't available, so use voice commands."
        return f"Recording started, sir.{extra}{bar}"

    def pause(self) -> str:
        with self._lock:
            if self.state == _PAUSED:
                return "The recording is already paused, sir."
            if self.state != _REC:
                return "There's no recording in progress, sir."
            self.take.pause_clock()
            self.state = _PAUSED
        self._notify()
        return "Recording paused."

    def resume(self) -> str:
        with self._lock:
            if self.state == _REC:
                return "The recording is already running, sir."
            if self.state != _PAUSED:
                return "There's no recording to resume, sir."
            self.take.resume_clock()
            self.state = _REC
        self._notify()
        return "Recording resumed."

    def stop(self, quiet: bool = False) -> str:
        with self._lock:
            if self.state not in (_REC, _PAUSED):
                return "There's no recording in progress, sir."
            take = self.take
            self.state = _SAVING
        self._notify()
        try:
            path, secs = take.finish(_out_dir())
        except Exception as e:
            take.abort()
            with self._lock:
                self.take, self.state = None, _IDLE
                self.error = str(e)[:90]
            self._notify()
            raise
        with self._lock:
            self.take, self.state = None, _IDLE
            self.result = (path, secs)
        self._notify()
        self.log(f"SYS: Recording saved → {path}")
        return (f"Recording saved, sir. {_spoken(secs)}, in your Videos folder "
                f"under {FOLDER_NAME}.")

    def restart(self) -> str:
        with self._lock:
            if self.state not in (_REC, _PAUSED):
                return "There's no recording to restart, sir. Say 'record my screen' to begin."
            take = self.take
            self.take = None
            self.state = _STARTING
        self._notify()
        take.abort()
        msg = self._launch()
        return "Started over, sir — the previous take was discarded. " + msg.replace(
            "Recording started, sir. ", "")

    def status(self) -> str:
        st, el, _ = self.snapshot()
        if st == _REC:
            return f"Recording, sir — {_spoken(el)} so far."
        if st == _PAUSED:
            return f"The recording is paused at {_spoken(el)}, sir."
        if st in (_STARTING, _SAVING):
            return "The recorder is busy for a moment, sir."
        if self.result:
            return (f"Not recording, sir. The last one was {_spoken(self.result[1])} "
                    f"and is in your Videos folder.")
        return "Not recording, sir."

    def open_folder(self) -> str:
        d = _out_dir()
        _ui_call(lambda: _open_path(d))
        if not _ui_available():
            try:
                if _IS_WIN:
                    os.startfile(str(d))                     # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(d)])
                else:
                    subprocess.Popen(["xdg-open", str(d)])
            except Exception as e:
                return f"I couldn't open the folder, sir: {e}"
        return "Opening your recordings folder, sir."

    # -- callbacks from worker threads ----------------------------------------
    def on_limit(self, take: _Take) -> None:
        def go():
            self.say(f"The screen recording hit its {MAX_MINUTES // 60}-hour safety limit and was "
                     "saved automatically. Tell the user briefly.")
            try:
                self.stop()
            except Exception as e:
                self.log(f"SYS: Auto-stop failed: {e}")
        if self.take is take:
            threading.Thread(target=go, daemon=True).start()

    def on_failure(self, take: _Take, why: str) -> None:
        def go():
            with self._lock:
                if self.take is not take or self.state not in (_REC, _PAUSED):
                    return
                self.take, self.state = None, _IDLE
                self.error = why[:90]
            take.abort()
            self._notify()
            self.log(f"SYS: Screen recording failed — {why}")
            self.say(f"The screen recording stopped unexpectedly ({why}). Tell the user briefly.")
        threading.Thread(target=go, daemon=True).start()

    # -- button-driven actions (run off the Qt thread, speak the outcome) -------
    def from_bar(self, what: str) -> None:
        def go():
            try:
                if what == "pause":
                    self.pause()
                elif what == "resume":
                    self.resume()
                elif what == "start":
                    self.start()
                elif what == "restart":
                    self.restart()
                elif what == "stop":
                    path_msg = self.stop()
                    self.say("The user just pressed Stop on the recording bar and the screen "
                             "recording was saved to their Videos folder. Confirm in one short "
                             "sentence. " + path_msg)
            except Exception as e:
                self.log(f"SYS: Screen recorder: {e}")
        threading.Thread(target=go, name="rec-bar-action", daemon=True).start()


RECORDER = _Recorder()


def _on_exit() -> None:
    try:
        if RECORDER.state in (_REC, _PAUSED):
            RECORDER.stop()                  # keep whatever was recorded
    except Exception:
        pass


atexit.register(_on_exit)


# ── Qt control bar ────────────────────────────────────────────────────────────
# Everything below that touches a widget runs on the Qt GUI thread. Plugin code runs on worker
# threads, so calls are marshalled through a queued signal on a QObject that lives in the GUI thread.

_bridge = None
_bridge_tried = False
_bar = None
_bar_pos = None


def _get_bridge():
    global _bridge, _bridge_tried
    if _bridge is not None or _bridge_tried:
        return _bridge
    _bridge_tried = True
    try:
        from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal, pyqtSlot
        app = QCoreApplication.instance()
        if app is None:
            _bridge_tried = False
            return None

        class _Bridge(QObject):
            call = pyqtSignal(object)

            def __init__(self):
                super().__init__()
                self.call.connect(self._run)

            @pyqtSlot(object)
            def _run(self, fn):
                try:
                    fn()
                except Exception:
                    traceback.print_exc()

        b = _Bridge()
        b.moveToThread(app.thread())
        _bridge = b
    except Exception:
        _bridge = None
    return _bridge


def _ui_available() -> bool:
    return _get_bridge() is not None


def _ui_call(fn) -> None:
    """Run fn() on the Qt thread, fire-and-forget. Silently does nothing if Qt isn't there."""
    b = _get_bridge()
    if b is not None:
        try:
            b.call.emit(fn)
        except Exception:
            pass


def _open_path(p: Path) -> None:
    try:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
    except Exception:
        pass


def _bar_refresh() -> None:                                # runs on the Qt thread
    global _bar
    try:
        st, _, info = RECORDER.snapshot()
        if _bar is None:
            if st == _IDLE and not info:
                return
            _bar = _make_bar_class()()
        _bar.refresh()
    except Exception:
        traceback.print_exc()


def _make_bar_class():
    from PyQt6.QtCore import QRectF, Qt, QTimer
    from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

    try:                                                   # match the HUD's current palette
        from ui import C
        pal = dict(bg=C.PANEL, border=C.BORDER_B, line=C.BORDER, text=C.TEXT, dim=C.TEXT_DIM,
                   pri=C.PRI, ghost=C.PRI_GHO, red=C.RED, amber=C.ACC2, green=C.GREEN)
    except Exception:
        pal = dict(bg="#010d14", border="#1a5c7a", line="#0d3347", text="#8ffcff", dim="#3a8a9a",
                   pri="#00d4ff", ghost="#001f2e", red="#ff3355", amber="#ffcc00", green="#00ff88")

    css = f"""
        QLabel {{ color: {pal['text']}; font: 600 10pt "Segoe UI"; background: transparent; }}
        QLabel#time {{ font: 700 11pt "Consolas"; min-width: 52px; }}
        QLabel#info {{ color: {pal['dim']}; font: 9pt "Segoe UI"; }}
        QPushButton {{
            background: {pal['ghost']}; color: {pal['text']};
            border: 1px solid {pal['line']}; border-radius: 9px;
            padding: 5px 11px; font: 600 9pt "Segoe UI";
        }}
        QPushButton:hover {{ border-color: {pal['pri']}; }}
        QPushButton:pressed {{ background: {pal['line']}; }}
        QPushButton:disabled {{ color: {pal['dim']}; border-color: {pal['line']}; }}
        QPushButton#danger {{ color: {pal['red']}; border-color: {pal['red']}; }}
        QPushButton#flat {{ border: none; background: transparent; padding: 4px 7px; }}
    """

    class RecordingBar(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setStyleSheet(css)
            self._drag = None
            self._blink = False
            self._armed = False

            row = QHBoxLayout(self)
            row.setContentsMargins(14, 8, 12, 8)
            row.setSpacing(8)

            self.dot = QLabel("●")
            self.time = QLabel("00:00")
            self.time.setObjectName("time")
            self.info = QLabel("")
            self.info.setObjectName("info")

            self.b_pause = self._btn("⏸ Pause", lambda: self._act("pause"))
            self.b_stop = self._btn("⏹ Stop", lambda: self._act("stop"), "danger")
            self.b_restart = self._btn("↻ Restart", self._restart_clicked)
            self.b_start = self._btn("⏺ Start", lambda: self._act("start"))
            self.b_folder = self._btn("📂", lambda: _open_path(_out_dir()), "flat")
            self.b_close = self._btn("✕", self.hide, "flat")
            self.b_folder.setToolTip("Open recordings folder")

            for wdg in (self.dot, self.time, self.info, self.b_pause, self.b_stop,
                        self.b_restart, self.b_start, self.b_folder, self.b_close):
                row.addWidget(wdg)

            self._tick_timer = QTimer(self)
            self._tick_timer.setInterval(250)
            self._tick_timer.timeout.connect(self._tick)
            self._tick_timer.start()

            self._hide_timer = QTimer(self)
            self._hide_timer.setSingleShot(True)
            self._hide_timer.setInterval(9000)
            self._hide_timer.timeout.connect(self.hide)

        # -- building blocks
        def _btn(self, text, slot, name=None):
            b = QPushButton(text)
            if name:
                b.setObjectName(name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False: slot())
            return b

        def _act(self, what):
            RECORDER.from_bar(what)

        def _restart_clicked(self):
            # Restart discards the take, so it takes two clicks within 3 s.
            if not self._armed:
                self._armed = True
                self.b_restart.setText("Discard & restart?")
                QTimer.singleShot(3000, self._disarm)
                return
            self._disarm()
            self._act("restart")

        def _disarm(self):
            self._armed = False
            self.b_restart.setText("↻ Restart")

        # -- state
        def refresh(self):
            st, el, info = RECORDER.snapshot()
            rec, paused = st == _REC, st == _PAUSED
            live = rec or paused
            busy = st in (_STARTING, _SAVING)

            for wdg, vis in ((self.b_pause, live), (self.b_stop, live), (self.b_restart, live),
                             (self.b_start, st == _IDLE), (self.b_folder, st == _IDLE),
                             (self.b_close, st == _IDLE)):
                wdg.setVisible(vis)
            self.b_pause.setText("▶ Resume" if paused else "⏸ Pause")
            self.b_pause.clicked.disconnect()
            self.b_pause.clicked.connect(lambda _=False, w=("resume" if paused else "pause"): self._act(w))
            if not live:
                self._disarm()

            self.time.setVisible(live)
            self.time.setText(_clock(el))
            self.info.setText({"starting": "Starting…", "saving": "Saving…"}.get(st, info))
            self.info.setVisible(bool(self.info.text()))
            self.dot.setStyleSheet(f"color: {pal['amber'] if paused else pal['red'] if live else pal['green'] if info.startswith('Saved') else pal['dim']};")
            self.dot.setText("●" if (live or busy) else ("✓" if info.startswith("Saved") else "●"))

            if st == _IDLE:
                self._hide_timer.start()
            else:
                self._hide_timer.stop()

            self.adjustSize()
            if not self.isVisible():
                self._place()
                self.show()
            self._exclude_from_capture()

        def _tick(self):
            st, el, _ = RECORDER.snapshot()
            if st in (_REC, _PAUSED):
                self.time.setText(_clock(el))
                if st == _REC:
                    self._blink = not self._blink
                    self.dot.setStyleSheet(
                        f"color: {pal['red'] if self._blink else pal['dim']};")

        def _place(self):
            if _bar_pos is not None:
                self.move(_bar_pos)
                return
            scr = QGuiApplication.primaryScreen().availableGeometry()
            self.move(scr.x() + (scr.width() - self.width()) // 2, scr.y() + 14)

        def _exclude_from_capture(self):
            """Windows 10 2004+: keep this window out of screen capture (WDA_EXCLUDEFROMCAPTURE)."""
            if not _IS_WIN:
                return
            try:
                ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x00000011)
            except Exception:
                pass

        # -- painting + dragging
        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            fill = QColor(pal["bg"])
            fill.setAlpha(238)
            p.setBrush(fill)
            p.setPen(QPen(QColor(pal["border"]), 1.3))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 15, 15)

        def mousePressEvent(self, e):
            if e.button() == Qt.MouseButton.LeftButton:
                self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                e.accept()

        def mouseMoveEvent(self, e):
            if self._drag is not None and (e.buttons() & Qt.MouseButton.LeftButton):
                self.move(e.globalPosition().toPoint() - self._drag)
                e.accept()

        def mouseReleaseEvent(self, e):
            global _bar_pos
            if self._drag is not None:
                _bar_pos = self.pos()
            self._drag = None

    return RecordingBar


# ── Tool entry point ──────────────────────────────────────────────────────────

_ACTIONS = {
    "start": "start", "begin": "start", "record": "start", "go": "start", "on": "start",
    "stop": "stop", "end": "stop", "finish": "stop", "save": "stop", "halt": "stop",
    "pause": "pause", "hold": "pause",
    "resume": "resume", "continue": "resume", "unpause": "resume",
    "restart": "restart", "redo": "restart", "retake": "restart", "again": "restart",
    "status": "status", "state": "status", "check": "status",
    "open_folder": "open_folder", "open": "open_folder", "folder": "open_folder",
    "show": "open_folder",
}


def _norm_audio(v) -> str | None:
    s = str(v or "").strip().lower()
    if not s:
        return None
    if any(k in s for k in ("none", "no audio", "mute", "silent", "without", "off")):
        return "none"
    if any(k in s for k in ("both", "all", "everything")):
        return "both"
    if "mic" in s or "voice" in s:
        return "mic"
    if any(k in s for k in ("system", "desktop", "internal", "speaker", "computer")):
        return "system"
    return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Never raises — always returns a short sentence for JARVIS to speak."""
    try:
        parameters = parameters or {}
        if player is not None:
            RECORDER.player = player
        action = _ACTIONS.get(str(parameters.get("action", "")).strip().lower().replace(" ", "_"))
        audio = _norm_audio(parameters.get("audio"))
        if action is None:
            return ("Sir, tell me whether to start, stop, pause, resume or restart the recording.")

        if action == "start":
            result = RECORDER.start(audio)
        elif action == "stop":
            result = RECORDER.stop()
        elif action == "pause":
            result = RECORDER.pause()
        elif action == "resume":
            result = RECORDER.resume()
        elif action == "restart":
            if audio:
                RECORDER.audio_mode = audio
            result = RECORDER.restart()
        elif action == "status":
            result = RECORDER.status()
        else:
            result = RECORDER.open_folder()
        return result
    except _RecError as e:
        return f"Sir, {e}"
    except Exception as e:                                     # last-resort safety net
        traceback.print_exc()
        return f"Sir, the screen recorder failed: {e}"
