"""Text-to-speech: read an arbitrary reply aloud.

Two backends, tried in order:
  1. Voice clone — a local GPT-SoVITS service (see D:/Dev/voiceclone/serve.py)
     that speaks in Amiya's own cloned voice. Preferred when running.
  2. edge-tts — Microsoft's online neural voices (needs network, no key).

Synthesis runs on a background QThread so the UI never blocks; when the audio
file is ready a signal fires and the window plays it through the VoicePlayer,
so the same volume/mute controls apply. If both backends fail, the caller
falls back to a fixed in-game voice line.
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import urllib.request

from PyQt5 import QtCore

try:
    import edge_tts
    _AVAILABLE = True
except Exception:  # dependency missing in this environment
    _AVAILABLE = False

# A warm Chinese female neural voice that suits Amiya.
DEFAULT_VOICE = "zh-CN-XiaoyiNeural"

# Local voice-clone service (Amiya's own voice).
CLONE_URL = os.environ.get("AMIYA_TTS_URL", "http://127.0.0.1:9881")

# Shared-secret header. The clone service binds to loopback, but that still
# leaves it reachable by *any* local process — including JavaScript in a
# browser, which can issue a no-preflight POST and drive GPU synthesis. Both
# sides read the same token file, so the secret works no matter how serve.py
# was launched (by us, or by hand from its own venv).
TOKEN_HEADER = "X-Amiya-Token"
_clone_token = None


def _token_path():
    from .settings import config_dir
    return os.path.join(config_dir(), "tts_token")


def clone_token():
    """Return the shared secret for the clone service, creating it if needed.

    Returns None if it can't be read or created, in which case requests go out
    unauthenticated (and a token-enforcing service will reject them) rather
    than the pet losing its voice outright.
    """
    global _clone_token
    if _clone_token:
        return _clone_token
    env = os.environ.get("AMIYA_TTS_TOKEN")
    if env:
        _clone_token = env.strip()
        return _clone_token
    path = _token_path()
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            _clone_token = tok
            return tok
    except Exception:
        pass
    try:
        import secrets
        tok = secrets.token_urlsafe(32)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(tok)
        os.replace(tmp, path)      # atomic on same volume
        _clone_token = tok
        return tok
    except Exception:
        return None


def available():
    return _AVAILABLE


def clone_ready(timeout=0.6):
    """True if the local voice-clone service is reachable."""
    try:
        with urllib.request.urlopen(CLONE_URL + "/ping", timeout=timeout) as r:
            return r.read().strip() == b"ok"
    except Exception:
        return False


def clone_character(timeout=0.6):
    """Return the character key the running service was launched with, or None.

    Used to detect when the service is up but loaded a different character's
    fine-tuned model, so we can restart it for the current character.
    """
    try:
        with urllib.request.urlopen(CLONE_URL + "/character",
                                    timeout=timeout) as r:
            return json.loads(r.read() or b"{}").get("key")
    except Exception:
        return None


_clone_proc = None
_clone_pid = None            # PID of the serve.py process (always set, even when
                              # reusing a process we didn't launch, so shutdown
                              # can always kill it)
_clone_last_used = 0.0       # timestamp of last TTS request that used the clone
_manual_start = False        # True when the user started it from the menu; a
                              # manually started service must NOT be auto-stopped
                              # by the idle timeout (the model takes ~30s to load)

# Last-known clone service state, cached so menu code never blocks on a /ping.
# Refreshed off the UI thread by the background probe (pet.window.CloneStateProbe)
# and after explicit start/stop actions.
_clone_state_cache = "stopped"

# Default location of the voice-clone project (venv + serve.py + models).
CLONE_DIR = os.environ.get("AMIYA_CLONE_DIR", "voiceclone")


def clone_state():
    """Last-known clone service state: 'running', 'starting', or 'stopped'.

    'starting' means we launched serve.py but the model is still loading (the
    first /ping answers only after ~30s). The context menu uses this to label
    the manual start/stop control correctly.

    Non-blocking: a synchronous probe used to run here and froze the GUI for
    up to 0.6 s on every right-click while the service was starting. State is
    now refreshed off the UI thread via refresh_clone_state().
    """
    return _clone_state_cache


def refresh_clone_state():
    """Probe the clone service and update the cached state.

    May block up to the /ping timeout (0.6 s) — call from a worker thread (see
    pet.window.CloneStateProbe). Returns the updated state.
    """
    global _clone_state_cache
    try:
        if clone_ready():
            _clone_state_cache = "running"
        elif _clone_proc is not None and _clone_proc.poll() is None:
            _clone_state_cache = "starting"
        else:
            _clone_state_cache = "stopped"
    except Exception:
        pass  # keep the last-known state rather than crash the probe
    return _clone_state_cache


def set_clone_state(state):
    """Record a known state change (e.g. right after start/stop). Non-blocking."""
    global _clone_state_cache
    _clone_state_cache = state


# ── temp audio files ───────────────────────────────────────────────
# Synthesized speech is the *content of the user's AI conversation*, so the
# files get unpredictable names (mkstemp + O_EXCL, which also stops a local
# process from pre-creating the path as a symlink to redirect our write) and
# are deleted once they are no longer being played.
_tmp_files = []              # paths we created, oldest first
_TMP_KEEP = 2                # keep the newest N (one may still be playing)


def _new_tmp_path(suffix):
    """Create an empty temp file with an unguessable name; return its path."""
    fd, path = tempfile.mkstemp(prefix="amiya_tts_", suffix=suffix)
    os.close(fd)
    _tmp_files.append(path)
    return path


def _prune_tmp_files(keep=_TMP_KEEP):
    """Delete our older temp audio files, keeping the newest `keep`."""
    while len(_tmp_files) > keep:
        path = _tmp_files.pop(0)
        try:
            os.remove(path)
        except OSError:
            pass  # still locked by the player; it goes on the next pass


def cleanup_temp_files():
    """Delete every temp audio file we created. Call on app shutdown."""
    _prune_tmp_files(keep=0)


def clone_touch():
    """Mark the clone service as recently used (resets the idle auto-stop)."""
    global _clone_last_used
    _clone_last_used = time.time()


def maybe_stop_idle_clone(idle_seconds: float = 600) -> bool:
    """Stop the clone service if it hasn't been used for `idle_seconds`.

    Returns True if the service was stopped, False otherwise.  Call this
    periodically from the main loop (e.g. every 30 s) to free GPU memory
    when TTS hasn't been used in a while.

    A service the user started manually from the context menu is never
    auto-stopped — they explicitly asked for it and reloading the model takes
    ~30 s; only automatically-launched instances get an idle timeout.
    """
    global _clone_last_used, _clone_proc
    if _manual_start:
        return False
    if _clone_last_used <= 0:
        return False
    elapsed = time.time() - _clone_last_used
    if elapsed < idle_seconds:
        return False
    if _clone_proc is not None or clone_ready(timeout=0.3):
        _stop_clone_service()
        _clone_last_used = 0.0
        return True
    _clone_last_used = 0.0
    return False


def _resolve_clone_dir(base_dir):
    """Resolve clone_dir relative to the exe/script root when not absolute.

    This lets packaging (installer / zip) put voiceclone next to the exe and set
    a relative clone_dir in the character config — no env var or hardcoded path
    needed.
    """
    if base_dir and not os.path.isabs(base_dir):
        if getattr(sys, "frozen", False):
            root = os.path.dirname(sys.executable)
        else:
            # Script is at pet/tts.py, project root is one level up.
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.normpath(os.path.join(root, base_dir))
    return base_dir


def _find_pid_on_port(port):
    """Return the PID of the process LISTENING on `port`, or None."""
    if os.name != "nt":
        return None
    try:
        import subprocess
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            creationflags=0x08000000).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[3] != "LISTENING":
                continue
            if parts[1].rsplit(":", 1)[-1] != str(port):
                continue
            if parts[-1].isdigit() and parts[-1] != "0":
                return int(parts[-1])
    except Exception:
        pass
    return None


def start_clone_service(clone_dir=None, character=None, manual=False):
    """Launch the local voice-clone service if it isn't already running.

    Non-blocking: the model load takes ~30s. Until it's ready, replies use
    edge-tts; once /ping answers, the worker switches to the cloned voice.
    Returns True if a service is running or was launched.

    `character` (e.g. "shenglinchuxue") is passed to serve.py as
    `--character`, so the service loads that character's fine-tuned model and
    reference audio. This is what makes the trained voice (not a generic
    zero-shot clone) come out.

    `manual=True` marks the service as user-started: the idle auto-stop then
    leaves it alone until the user stops it explicitly from the menu.
    """
    global _clone_proc, _clone_pid, _manual_start
    if manual:
        _manual_start = True
    if clone_ready():
        # Service is up. Verify it loaded the character we need; if not,
        # restart it so the correct fine-tuned model is used.
        if character:
            running = clone_character()
            if running == character:
                # Track the PID even when reusing, so shutdown can kill it.
                if _clone_pid is None:
                    _clone_pid = _find_pid_on_port(_clone_port())
                return True
            _stop_clone_service()  # wrong or unknown character -> restart
        else:
            if _clone_pid is None:
                _clone_pid = _find_pid_on_port(_clone_port())
            return True
    base = _resolve_clone_dir(clone_dir or CLONE_DIR)
    if base is None:
        return False
    py = os.path.join(base, ".venv", "Scripts", "python.exe")
    serve = os.path.join(base, "serve.py")
    if not (os.path.isfile(py) and os.path.isfile(serve)):
        return False
    if _clone_proc is not None and _clone_proc.poll() is None:
        return True  # already launched by us, still starting up
    try:
        import subprocess
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        cmd = [py, serve]
        if character:
            cmd += ["--character", character]
        _clone_proc = subprocess.Popen(
            cmd, cwd=base, creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _clone_pid = _clone_proc.pid
        return True
    except Exception:
        return False


def stop_clone_service(timeout=5):
    """Stop the clone service and free its resources.

    Call this on app shutdown so the voice-clone Python process doesn't keep
    running in the background consuming memory after the pet window is closed.

    First stops our own subprocess if we launched it. If a *stale* service
    (started by some other path, e.g. an old auto-start) is still holding the
    port, kill whatever is listening on it — otherwise the port stays occupied
    and our restart with the correct --character can't bind, leaving the wrong
    voice active. Best-effort; failures are swallowed.
    """
    _stop_clone_service(timeout=timeout)


def _stop_clone_service(timeout=5):
    """Internal: stop the clone subprocess + free the port if a stale listener
    remains."""
    global _clone_proc, _clone_pid, _manual_start
    _manual_start = False   # 停掉后回到「可自动停」状态，下次自动拉起照常超时
    # 1. Kill by PID — always works, even when we reused a process we didn't
    #    launch (in which case _clone_proc is None but _clone_pid is tracked).
    if _clone_pid is not None:
        if os.name == "nt":
            try:
                import subprocess
                subprocess.run(["taskkill", "/f", "/pid", str(_clone_pid)],
                               capture_output=True,
                               creationflags=0x08000000)
            except Exception:
                pass
        else:
            try:
                import signal
                os.kill(_clone_pid, signal.SIGTERM)
            except Exception:
                pass
    # 2. Terminate our own subprocess handle (if we launched it).
    if _clone_proc is not None:
        if _clone_proc.poll() is None:
            try:
                _clone_proc.terminate()
                _clone_proc.wait(timeout=timeout)
            except Exception:
                try:
                    _clone_proc.kill()
                except Exception:
                    pass
    _clone_proc = None
    _clone_pid = None
    # 3. Last resort: if something is still listening on the port, hunt it down
    #    via netstat (catches stale processes from other sessions).
    if clone_ready(timeout=1.0):
        _kill_listeners_on_clone_port()


def _clone_port(default=9881):
    """Parse the port from CLONE_URL (http://host:port).

    Refuses privileged ports: the port drives a taskkill below, and CLONE_URL
    comes from an env var, so a value like ":445" would make us hunt down a
    system service.  Anything outside the unprivileged range falls back to the
    default.
    """
    try:
        port = int(CLONE_URL.rsplit(":", 1)[-1].split("/")[0])
    except Exception:
        return default
    return port if 1024 <= port <= 65535 else default


def _kill_listeners_on_clone_port():
    """Kill any process LISTENING on the clone port (Windows only, best-effort).

    Guards against stale serve.py instances that were launched with the wrong
    character and still occupy the port.
    """
    if os.name != "nt":
        return
    port = _clone_port()
    try:
        import subprocess
        # netstat -> find LISTENING PIDs on :port, then taskkill each.
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            creationflags=0x08000000).stdout
        pids = set()
        for line in out.splitlines():
            # Columns: proto  local-addr  foreign-addr  state  pid
            # Match positionally on the LOCAL address only.  A substring
            # search would also hit a *foreign* address ending in :port and
            # then force-kill an unrelated process.
            parts = line.split()
            if len(parts) < 5 or parts[3] != "LISTENING":
                continue
            if parts[1].rsplit(":", 1)[-1] != str(port):
                continue
            if parts[-1].isdigit() and parts[-1] != "0":
                pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/f", "/pid", pid],
                           capture_output=True, creationflags=0x08000000)
        # Give the OS a moment to release the socket (TIME_WAIT).
        import time as _t
        _t.sleep(1.5)
    except Exception:
        pass


def _clone_synthesize(text, out_path, character=None, timeout=60):
    """Ask the clone service to synthesize `text` into `out_path` (wav).

    If `character` is given (e.g. "shenglinchuxue"), the service uses that
    character's reference audio for zero-shot cloning.
    """
    payload = {"text": text}
    if character:
        payload["character"] = character
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = clone_token()
    if token:
        headers[TOKEN_HEADER] = token
    req = urllib.request.Request(
        CLONE_URL + "/tts", data=body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if not data.startswith(b"RIFF"):   # error json, not audio
        return False
    with open(out_path, "wb") as f:
        f.write(data)
    return os.path.getsize(out_path) > 0


def _synthesize(text, out_path, voice, rate, volume, pitch):
    """Blocking synthesis into `out_path` (mp3). Returns True on success."""
    if not _AVAILABLE or not (text or "").strip():
        return False

    async def go():
        comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume,
                                    pitch=pitch)
        await comm.save(out_path)

    asyncio.run(go())
    return os.path.isfile(out_path) and os.path.getsize(out_path) > 0


class TtsWorker(QtCore.QThread):
    """Synthesizes `text` off the UI thread; emits the audio path or ''.

    Tries the voice-clone service first (Amiya's own voice), then edge-tts.
    """

    done = QtCore.pyqtSignal(str)  # path on success, '' on failure

    def __init__(self, text, voice=DEFAULT_VOICE, rate="+0%", volume="+0%",
                 pitch="+0Hz", use_clone=True, clone_character=None,
                 parent=None):
        super().__init__(parent)
        self.text = text
        self.voice = voice or DEFAULT_VOICE
        self.rate = rate
        self.volume = volume
        self.pitch = pitch
        self.use_clone = use_clone
        self.clone_character = clone_character

    def run(self):
        try:
            # Drop files from earlier replies; the newest ones may still be
            # playing, so _prune_tmp_files keeps a couple around.
            _prune_tmp_files()
            # 1) voice clone (character's own voice) if the service is up
            if self.use_clone and clone_ready():
                if self.isInterruptionRequested():
                    return
                try:
                    clone_touch()          # reset idle auto-stop timer
                    wav = _new_tmp_path(".wav")
                    if _clone_synthesize(self.text, wav,
                                         character=self.clone_character):
                        self.done.emit(wav)
                        return
                except Exception:
                    pass  # fall through to edge-tts
            # 2) edge-tts fallback
            if self.isInterruptionRequested():
                return
            mp3 = _new_tmp_path(".mp3")
            ok = _synthesize(self.text, mp3, self.voice, self.rate,
                             self.volume, self.pitch)
            self.done.emit(mp3 if ok else "")
        except Exception:
            self.done.emit("")
