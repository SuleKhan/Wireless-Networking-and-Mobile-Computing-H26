"""
audio_watermark - hide a text message in audio, play it over the air, read it back.

    from Audio.audio_watermark import AudioWatermark, show_levels

    show_levels("CrabRave.wav")                       # what fits at each level
    wm   = AudioWatermark(level=2)                    # 1 = most robust ... 6 = most data
    sent = wm.embed("CrabRave.wav", "CrabRave_Encoded.wav", "Hello WNMC")
    got  = wm.decode("CrabRave_Recorded.wav", settings=sent)
    print(got.evaluate())                             # bit error rate, character accuracy, diff

The one knob is `level`. Every level spends the same watermark energy, so they all sound
alike; what changes is how many audio frames protect each bit. Fewer frames per bit leave
room for more characters but give each bit less protection: more data, less robustness.

Wraps audiowmark (github.com/swesterfeld/audiowmark) built with the WNMC capacity patch,
which adds --payload-size and --generators. See docker/ for the build.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

__all__ = ["AudioWatermark", "Level", "LEVELS", "show_levels", "capacity", "evaluate",
           "simulate_channel", "SCENARIOS", "check_audio_loop", "play_and_record",
           "list_audio_devices", "build_docker_image", "log_measurement", "setup", "BackendError"]

DOCKER_IMAGE = os.environ.get("AUDIO_WATERMARK_IMAGE", "wnmc-audiowmark")
DEFAULT_STRENGTH = 15   # audiowmark's default is 10; 15 measured PESQ ~4.6 (inaudible) and is more robust


# ----------------------------------------------------------------------------- levels
@dataclass(frozen=True)
class Level:
    number: int
    name: str
    generators: int        # convolutional code: even, 2..12 (12 = strongest)
    frames_per_bit: int    # audio frames spent on every coded bit

    @property
    def redundancy(self) -> int:
        """Audio frames spent per message bit. Higher = more robust, fewer characters."""
        return (self.generators // 2) * self.frames_per_bit


LEVELS = {
    1: Level(1, "very robust", 12, 3),
    2: Level(2, "robust", 12, 2),       # = audiowmark's own default
    3: Level(3, "balanced", 12, 1),
    4: Level(4, "fast", 10, 1),
    5: Level(5, "faster", 8, 1),
    6: Level(6, "maximum", 4, 1),
}

# audiowmark internals (wmcommon.hh / convcode.cc): it always works at 44.1 kHz in 1024-sample
# frames, spends 6 sync bits x 85 frames on synchronisation, and uses a code of order 15.
_MARK_SR, _FRAME, _SYNC_FRAMES, _ORDER = 44100, 1024, 6 * 85, 15


def _frames(seconds: float) -> int:
    return int(seconds * _MARK_SR / _FRAME)


def _block_frames(level: "Level", payload_bits: int) -> int:
    return _SYNC_FRAMES + (payload_bits + _ORDER) * level.redundancy


def _level(level) -> Level:
    if isinstance(level, Level):
        return level
    if level not in LEVELS:
        raise ValueError(f"level must be one of {list(LEVELS)}, got {level!r}")
    return LEVELS[level]


def capacity(level, seconds: float) -> dict:
    """Largest message that fits one complete watermark block in `seconds` of audio."""
    lv = _level(level)
    free = _frames(seconds) - _SYNC_FRAMES
    bits = free // lv.redundancy - _ORDER if free > 0 else 0
    bits = max(0, bits - bits % 8)                       # whole characters only
    return {"level": lv.number, "name": lv.name, "bits": bits, "chars": bits // 8,
            "bits_per_second": bits / seconds if seconds else 0.0, "redundancy": lv.redundancy}


def _duration(audio) -> float:
    if isinstance(audio, (int, float)):
        return float(audio)
    return sf.info(str(audio)).duration


def show_levels(audio="CrabRave.wav", message: str | None = None) -> None:
    """Print how many characters fit at each level for this clip (a file or a duration in seconds)."""
    secs = _duration(audio)
    need = len(message) if message is not None else None
    name = f"{secs:.0f} s of audio" if isinstance(audio, (int, float)) else Path(str(audio)).name
    head = f"Levels for {name} ({secs:.1f} s)"
    if need is not None:
        head += f" - your message has {need} characters"
    print(head)
    print(f"  {'level':<7}{'name':<13}{'frames/bit':>11}{'max chars':>11}{'bit/s':>8}")
    for lv in LEVELS.values():
        c = capacity(lv, secs)
        fits = "" if need is None else ("   fits" if need <= c["chars"] else "   too long")
        tag = "   (audiowmark default)" if lv.number == 2 else ""
        print(f"  {lv.number:<7}{lv.name:<13}{lv.redundancy:>11}{c['chars']:>11}"
              f"{c['bits_per_second']:>8.1f}{fits}{tag}")
    print("  frames/bit = audio frames protecting each message bit: more frames, more robust,"
          " fewer characters.")
    if need is not None:
        print("  A message shorter than the maximum is repeated more often in the clip, which also helps.")


# ----------------------------------------------------------------------------- message framing
_UNPRINTABLE = "·"    # shown for a received byte that is not printable text


def text_to_bits(text: str) -> np.ndarray:
    data = text.encode("ascii", errors="replace")        # 1 character = 8 bits
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8)).astype(np.uint8)


def bits_to_text(bits) -> str:
    bits = np.asarray(bits, dtype=np.uint8)
    bits = bits[: len(bits) // 8 * 8]
    # every position is kept: no dropping of bad bytes, no truncation at a zero byte
    return "".join(chr(b) if 32 <= b <= 126 else _UNPRINTABLE for b in np.packbits(bits))


def _to_hex(bits) -> str:
    return "".join(f"{int(''.join(map(str, bits[i:i + 4])), 2):x}" for i in range(0, len(bits), 4))


def _from_hex(h: str, nbits: int) -> np.ndarray:
    v = int(h, 16)
    return np.array([(v >> i) & 1 for i in reversed(range(nbits))], dtype=np.uint8)


# ----------------------------------------------------------------------------- results
@dataclass
class Evaluation:
    sent: str
    received: str
    bit_errors: int
    total_bits: int
    char_errors: int
    total_chars: int
    detected: bool

    @property
    def ber(self) -> float:
        return self.bit_errors / self.total_bits if self.total_bits else 0.0

    @property
    def char_accuracy(self) -> float:
        return 1 - self.char_errors / self.total_chars if self.total_chars else 0.0

    @property
    def perfect(self) -> bool:
        return self.detected and self.bit_errors == 0

    def diff(self) -> str:
        marks = "".join(" " if a == b else "^" for a, b in zip(self.sent, self.received))
        return f"  sent     : {self.sent}\n  received : {self.received}\n             {marks}"

    def __str__(self) -> str:
        if self.perfect:
            head = "perfect - every bit recovered"
        elif not self.detected:
            head = "no watermark found (BER counted as 0.5 = guessing)"
        else:
            head = f"{self.bit_errors} of {self.total_bits} bits wrong"
        return (f"{head}\n"
                f"  bit error rate     : {self.ber:.4f}  ({self.bit_errors}/{self.total_bits} bits)\n"
                f"  character accuracy : {self.char_accuracy:.1%}  "
                f"({self.total_chars - self.char_errors}/{self.total_chars} characters)\n"
                f"{self.diff()}")

    def as_row(self) -> dict:
        return {"ber": round(self.ber, 6), "bit_errors": self.bit_errors, "bits": self.total_bits,
                "char_accuracy": round(self.char_accuracy, 6), "chars": self.total_chars,
                "detected": self.detected}


def evaluate(sent: str, received) -> Evaluation:
    """Compare a sent message with a DecodeResult (or received text), bit by bit and position by position."""
    sbits = text_to_bits(sent)
    if isinstance(received, DecodeResult):
        rbits, detected = received.bits, received.detected
    else:
        rbits, detected = text_to_bits(str(received)), True
    if not detected or rbits is None:                   # nothing decoded: every bit is a coin flip
        n = len(sbits)
        return Evaluation(sent, _UNPRINTABLE * len(sent), n // 2, n, len(sent), len(sent), False)
    rbits = np.asarray(rbits, dtype=np.uint8)
    rbits = np.concatenate([rbits, np.zeros(max(0, len(sbits) - len(rbits)), np.uint8)])[: len(sbits)]
    rtext = bits_to_text(rbits)
    return Evaluation(sent, rtext, int(np.sum(sbits != rbits)), len(sbits),
                      sum(a != b for a, b in zip(sent, rtext)), len(sent), True)


@dataclass
class EmbedInfo:
    message: str
    output: str
    settings: dict
    seconds: float
    block_seconds: float
    repeats: float

    @property
    def settings_code(self) -> str:
        return f"L{self.settings['level']}:{self.settings['chars']}"

    def __str__(self) -> str:
        s = self.settings
        return (f"embedded {s['chars']} characters ({s['payload_bits']} bits) at level {s['level']} "
                f"({LEVELS[s['level']].name})\n"
                f"  output        : {self.output}\n"
                f"  one message   : {self.block_seconds:.1f} s of audio, fits {self.repeats:.1f}x "
                f"in this {self.seconds:.1f} s clip\n"
                f"  throughput    : {s['payload_bits'] / self.seconds:.1f} bit/s\n"
                f"  settings code : {self.settings_code}   (the receiver needs this to decode)")


@dataclass
class DecodeResult:
    text: str | None
    bits: np.ndarray | None
    detected: bool
    confidence: float
    settings: dict
    candidates: list = field(default_factory=list)

    def evaluate(self, sent: str | None = None) -> Evaluation:
        sent = sent if sent is not None else self.settings.get("message")
        if sent is None:
            raise ValueError("pass the message that was sent: result.evaluate('your message')")
        return evaluate(sent, self)

    def __str__(self) -> str:
        if not self.detected:
            return "no watermark found in this recording"
        return f'decoded: "{self.text}"   (confidence {self.confidence:.2f})'


# ----------------------------------------------------------------------------- backend
# Escape hatches for unusual machines (all optional):
#   AUDIO_WATERMARK_IMAGE   Docker image name                       (default: wnmc-audiowmark)
#   AUDIO_WATERMARK_BINARY  path to a patched native audiowmark     (skips Docker)
#   AUDIO_WATERMARK_TMP     folder Docker may mount for work files  (default: ~/.audio_watermark_tmp)
class BackendError(RuntimeError):
    pass


def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _docker_status() -> tuple:
    """('ok' | 'missing' | 'not_running' | 'permission', advice)."""
    if shutil.which("docker") is None:
        return "missing", ("Docker is not installed. Install Docker Desktop (Windows, macOS) or Docker "
                           "Engine (Linux): https://docs.docker.com/get-docker/")
    r = _run(["docker", "info"])
    if r.returncode == 0:
        return "ok", ""
    if "permission denied" in (r.stdout + r.stderr).lower():
        return "permission", ("Docker is installed but this user may not use it. On Linux run "
                              "'sudo usermod -aG docker $USER', then log out and back in.")
    return "not_running", ("Docker is installed but not running. Start Docker Desktop (Windows, macOS; "
                           "wait until it says 'running'), or on Linux: 'sudo systemctl start docker'.")


def _patched(cmd_prefix: list) -> bool:
    """The WNMC build rejects an odd generator count with a specific message; stock audiowmark doesn't."""
    try:
        r = _run(cmd_prefix + ["add", "--generators", "5", "a.wav", "b.wav", "00"], timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "must be even" in (r.stdout + r.stderr)


def _image_exists(image: str) -> bool:
    return _run(["docker", "image", "inspect", image]).returncode == 0


def _native_binary(binary: str | None = None) -> str | None:
    exe = binary or os.environ.get("AUDIO_WATERMARK_BINARY") or shutil.which("audiowmark")
    return exe if exe and _patched([exe]) else None


class _Backend:
    def __init__(self, image: str = DOCKER_IMAGE, binary: str | None = None):
        exe = _native_binary(binary)
        if exe:
            self.kind, self.exe = "native", exe
            return
        state, advice = _docker_status()
        if state != "ok":
            raise BackendError(advice + "\n  Then run setup() again.")
        if not _image_exists(image):
            raise BackendError(f"The watermark engine is not built yet (Docker image '{image}' is missing). "
                               f"Run setup() once: it compiles it, a few minutes, needs internet.")
        if not _patched(["docker", "run", "--rm", image]):
            raise BackendError(f"Docker image '{image}' is a stock audiowmark without the WNMC patch. "
                               f"Remove it ('docker rmi {image}') and run setup() again.")
        self.kind, self.image = "docker", image

    def run(self, args: list, workdir: str) -> subprocess.CompletedProcess:
        if self.kind == "native":
            return _run([self.exe] + args, cwd=workdir, timeout=1800)
        mount = str(Path(workdir).resolve()).replace("\\", "/")
        user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
        # --user: on Linux/macOS the files the engine writes belong to you, not to root
        return _run(["docker", "run", "--rm"] + user + ["-v", f"{mount}:/data", self.image] + args,
                    timeout=1800)


def build_docker_image(docker_dir: str | None = None, image: str = DOCKER_IMAGE) -> None:
    """Compile the watermark engine into a Docker image (needs Docker and internet; a few minutes, once)."""
    import time
    d = Path(docker_dir) if docker_dir else Path(__file__).resolve().parent / "docker"
    if not (d / "Dockerfile").exists():
        raise FileNotFoundError(f"no Dockerfile in {d}")
    state, advice = _docker_status()
    if state != "ok":
        raise BackendError(advice)
    print(f"Compiling the watermark engine into Docker image '{image}' - first time only, a few minutes.")
    t0, tail, seen = time.time(), [], set()
    for attempt in (["--progress=plain"], []):          # plain progress needs BuildKit (default today)
        proc = subprocess.Popen(["docker", "build"] + attempt + ["-t", image, str(d)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-40:]
            m = re.match(r"#\d+ \[(?:[\w-]+ )?(\d+)/(\d+)\] (.+)", line.strip())
            if m and m.group(3) not in seen:              # one line per build step
                seen.add(m.group(3))
                step = re.sub(r"\s+", " ", m.group(3))[:70]
                print(f"  [{time.time() - t0:5.0f} s] step {m.group(1)}/{m.group(2)}: {step}")
        rc = proc.wait()
        if rc == 0:
            break
        if attempt and any("unknown flag" in l for l in tail):
            continue                                      # old builder: retry without --progress
        break
    if rc != 0:
        joined = "\n".join(tail)
        hint = ("\n  Looks like a network problem: the build downloads Debian packages and the "
                "audiowmark source from GitHub. Check the internet connection and try again."
                if re.search(r"(?i)could not resolve|unable to access|temporary failure|timed out", joined) else "")
        raise BackendError(f"docker build failed:\n{joined}{hint}")
    print(f"  done in {time.time() - t0:.0f} s: engine '{image}' is ready")


def _workdir_root() -> str | None:
    # Docker Desktop always shares the user's home folder with containers; the system temp folder is
    # not shared on macOS. AUDIO_WATERMARK_TMP overrides this if the home path gives Docker trouble.
    root = Path(os.environ.get("AUDIO_WATERMARK_TMP") or (Path.home() / ".audio_watermark_tmp"))
    try:
        root.mkdir(parents=True, exist_ok=True)
        return str(root)
    except OSError:
        return None


def setup(build: bool = True) -> bool:
    """Check everything the audio lab needs, and compile the watermark engine if it is missing.

    Prints a checklist. Returns True when embedding and decoding will work. Optional parts
    (phone recordings, recording with this computer) are reported but never make it fail.
    """
    import sys
    ok = True

    def line(status, text):
        print(f"  [{status}] {text}")

    print("Audio lab setup")
    v = sys.version_info
    line("ok" if v >= (3, 8) else "!!", f"Python {v.major}.{v.minor}.{v.micro}"
         + ("" if v >= (3, 8) else " - Python 3.8 or newer is required"))
    ok &= v >= (3, 8)

    exe = _native_binary()
    if exe:
        line("ok", f"watermark engine: native audiowmark ({exe})")
    else:
        state, advice = _docker_status()
        if state != "ok":
            line("!!", advice)
            ok = False
        elif _image_exists(DOCKER_IMAGE) and _patched(["docker", "run", "--rm", DOCKER_IMAGE]):
            line("ok", f"watermark engine: Docker image '{DOCKER_IMAGE}'")
        elif build:
            if _image_exists(DOCKER_IMAGE):
                _run(["docker", "rmi", DOCKER_IMAGE])      # a stock image under our name: replace it
            try:
                build_docker_image()
                line("ok", f"watermark engine: Docker image '{DOCKER_IMAGE}' (just compiled)")
            except BackendError as e:
                line("!!", f"compiling the watermark engine failed:\n{e}")
                ok = False
        else:
            line("!!", f"watermark engine not built yet - run setup() to compile it")
            ok = False

    if ok:                                                # prove it end to end on 30 s of noise
        try:
            with tempfile.TemporaryDirectory(dir=_workdir_root()) as wd:
                noise = np.random.default_rng(0).normal(0, 0.1, 44100 * 30)
                sf.write(os.path.join(wd, "probe.wav"), noise, 44100, subtype="PCM_16")
                wm = AudioWatermark(level=6)
                info = wm.embed(os.path.join(wd, "probe.wav"), os.path.join(wd, "probe_out.wav"), "ok")
                good = wm.decode(os.path.join(wd, "probe_out.wav"), info, detect_speed=False).text == "ok"
            line("ok" if good else "!!", "test embed + decode " + ("works" if good else "FAILED"))
            ok &= good
        except Exception as e:                            # noqa: BLE001 - report anything to the student
            line("!!", f"test embed + decode failed: {e}")
            ok = False

    line("ok" if _ffmpeg() else "--", "phone recordings (.m4a, .aac)" +
         (" can be decoded" if _ffmpeg() else ": not available - pip install imageio-ffmpeg, or record .wav"))
    try:
        import sounddevice as sd
        sd.query_devices()
        line("ok", "recording with this computer is available (optional)")
    except Exception:                                     # noqa: BLE001 - PortAudio may be missing on Linux
        line("--", "recording with this computer: not available (optional - fine if you record with a phone;"
                   " on Linux: sudo apt install libportaudio2)")
    print("Ready." if ok else "Not ready - fix the [!!] lines above, then run setup() again.")
    return ok


# ----------------------------------------------------------------------------- audio files
def _ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg          # pip install imageio-ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _readable_wav(src: str, workdir: str, name: str) -> str:
    """Copy src into workdir as a file audiowmark reads. Phone formats (m4a, aac, ...) go through ffmpeg."""
    dst = os.path.join(workdir, name)
    try:
        info = sf.info(src)
        if info.format in ("WAV", "WAVEX", "FLAC", "AIFF"):
            shutil.copyfile(src, dst)
            return dst
        data, sr = sf.read(src, always_2d=True)          # e.g. mp3 / ogg
        sf.write(dst, data, sr, subtype="FLOAT")
        return dst
    except Exception:
        ff = _ffmpeg()
        if ff is None:
            raise ValueError(f"cannot read '{src}'. Convert it to .wav, or install ffmpeg "
                             f"(pip install imageio-ffmpeg).")
        r = subprocess.run([ff, "-y", "-v", "error", "-i", src, "-c:a", "pcm_f32le", dst],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ValueError(f"ffmpeg could not convert '{src}': {r.stderr.strip()[:300]}")
        return dst


def _sidecar(path) -> Path:
    p = Path(path)
    return p.with_name(p.stem + ".wm.json")


# ----------------------------------------------------------------------------- main class
class AudioWatermark:
    """Embed and decode text messages.

    level    : 1 (most robust, fewest characters) ... 6 (most characters, least robust)
    strength : watermark loudness on audiowmark's scale. 15 was inaudible in tests (PESQ ~4.6);
               higher is more robust but eventually audible. Only used when embedding.
    """

    def __init__(self, level: int = 2, strength: float = DEFAULT_STRENGTH,
                 image: str = DOCKER_IMAGE, binary: str | None = None):
        self.level = _level(level)
        self.strength = float(strength)
        self._image, self._binary, self._backend = image, binary, None

    @property
    def backend(self) -> _Backend:
        if self._backend is None:
            self._backend = _Backend(self._image, self._binary)
        return self._backend

    def __repr__(self) -> str:
        return f"AudioWatermark(level={self.level.number} '{self.level.name}', strength={self.strength:g})"

    def capacity(self, audio) -> dict:
        return capacity(self.level, _duration(audio))

    @staticmethod
    def _opts(level: Level, payload_bits: int) -> list:
        return ["--payload-size", str(payload_bits), "--generators", str(level.generators),
                "--frames-per-bit", str(level.frames_per_bit)]

    # ------------------------------------------------------------------ embed
    def embed(self, source, output, message: str) -> EmbedInfo:
        """Hide `message` in `source`. `output` keeps the source's rate, channels and bit depth."""
        if not message:
            raise ValueError("message is empty")
        seconds = _duration(source)
        cap = capacity(self.level, seconds)
        if len(message) > cap["chars"]:
            fit = [lv.number for lv in LEVELS.values() if capacity(lv, seconds)["chars"] >= len(message)]
            hint = (f" Levels that fit it: {fit}." if fit else
                    " No level fits it in this clip: use a longer clip or a shorter message.")
            raise ValueError(f"message has {len(message)} characters, but level {self.level.number} "
                             f"({self.level.name}) fits {cap['chars']} in {seconds:.1f} s.{hint}")
        bits = text_to_bits(message)
        with tempfile.TemporaryDirectory(dir=_workdir_root()) as wd:
            _readable_wav(str(source), wd, "in.wav")
            r = self.backend.run(["add", "--strength", f"{self.strength:g}"]
                                 + self._opts(self.level, len(bits))
                                 + ["in.wav", "out.wav", _to_hex(bits)], wd)
            out_tmp = os.path.join(wd, "out.wav")
            if r.returncode != 0 or not os.path.exists(out_tmp):
                raise BackendError(f"audiowmark add failed:\n{(r.stdout + r.stderr)[-800:]}")
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            if Path(output).suffix.lower() == ".wav":
                shutil.copyfile(out_tmp, output)
            else:                                       # e.g. .flac: rewrite in the requested container
                data, sr = sf.read(out_tmp, always_2d=True)
                sf.write(str(output), data, sr)
        block = _block_frames(self.level, len(bits)) * _FRAME / _MARK_SR
        settings = {"tool": "audio_watermark", "version": 1, "level": self.level.number,
                    "generators": self.level.generators, "frames_per_bit": self.level.frames_per_bit,
                    "strength": self.strength, "payload_bits": int(len(bits)), "chars": len(message),
                    "message": message, "source": Path(str(source)).name,
                    "created": datetime.datetime.now().isoformat(timespec="seconds")}
        _sidecar(output).write_text(json.dumps(settings, indent=1))
        return EmbedInfo(message, str(output), settings, seconds, block, seconds / block)

    # ------------------------------------------------------------------ decode
    @staticmethod
    def load_settings(settings) -> dict:
        """Accepts an EmbedInfo, a dict, a marked audio file (reads its .wm.json), or a code like 'L3:12'."""
        if isinstance(settings, EmbedInfo):
            return dict(settings.settings)
        if isinstance(settings, dict):
            return dict(settings)
        if isinstance(settings, (str, Path)):
            s = str(settings).strip()
            m = re.fullmatch(r"L(\d):(\d+)", s)
            if m:
                lv, n = _level(int(m.group(1))), int(m.group(2))
                return {"level": lv.number, "generators": lv.generators,
                        "frames_per_bit": lv.frames_per_bit, "payload_bits": 8 * n, "chars": n}
            side = Path(s) if s.endswith(".wm.json") else _sidecar(s)
            if side.exists():
                return json.loads(side.read_text())
            raise FileNotFoundError(f"no settings found for '{s}' (looked for {side}). "
                                    f"Pass the result of embed(), or a code like 'L2:10'.")
        raise TypeError("settings must be the result of embed(), a dict, a marked file, or a code like 'L2:10'")

    def decode(self, recording, settings, detect_speed: bool = True) -> DecodeResult:
        """Read the message back from a recording (wav, flac, mp3; m4a/aac via ffmpeg)."""
        s = self.load_settings(settings)
        lv = Level(s["level"], LEVELS[s["level"]].name, s["generators"], s["frames_per_bit"])
        nbits = int(s["payload_bits"])
        with tempfile.TemporaryDirectory(dir=_workdir_root()) as wd:
            _readable_wav(str(recording), wd, "rec.wav")
            args = ["get"] + self._opts(lv, nbits) + (["--detect-speed"] if detect_speed else [])
            r = self.backend.run(args + ["--json", "res.json", "rec.wav"], wd)
            res = os.path.join(wd, "res.json")
            if r.returncode != 0 or not os.path.exists(res):
                raise BackendError(f"audiowmark get failed:\n{(r.stdout + r.stderr)[-800:]}")
            with open(res) as fh:
                matches = json.load(fh).get("matches", [])
        good = [m for m in matches if len(m.get("bits", "")) * 4 == nbits]
        if not good:
            return DecodeResult(None, None, False, 0.0, s, matches)
        best = max(good, key=lambda m: m.get("rating", 0.0))      # audiowmark's own confidence
        bits = _from_hex(best["bits"], nbits)
        return DecodeResult(bits_to_text(bits), bits, True, float(best.get("rating", 0.0)), s, good)


def log_measurement(csv_path, distance_cm: float, result: "DecodeResult", sent: str | None = None,
                    note: str = "") -> dict:
    """Append one measurement to a CSV (created with a header if missing) and return the row.

    Columns: distance_cm, level, level_name, chars, ber, bit_errors, bits, char_accuracy,
    detected, confidence, note.
    """
    import csv
    ev = result.evaluate(sent)
    s = result.settings
    row = {"distance_cm": distance_cm, "level": s["level"], "level_name": LEVELS[s["level"]].name,
           "chars": s["chars"], **ev.as_row(), "confidence": round(result.confidence, 3), "note": note}
    path = Path(csv_path)
    new = not path.exists()
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    return row


# ----------------------------------------------------------------------------- simulated room
# `snr` is an EFFECTIVE signal-to-noise ratio: it lumps speaker distortion, room noise and
# microphone noise into one number. It was calibrated against real recordings (a monitor speaker
# and a Rode NT-USB) so that each level fails where it failed on that hardware: at 10 cm levels 2-4
# were clean and level 5 started to fail; at 50 cm level 2 was clean and levels 3-5 failed.
# The other distances are extrapolated from those two measured points.
SCENARIOS = {   # distance, reverb time, effective SNR, speaker low cut, mic high cut, clock drift, level drop
    "10cm": dict(distance=0.10, rt60=0.30, snr=11.0, low_cut=90, high_cut=17000, ppm=6, drop=-2),
    "25cm": dict(distance=0.25, rt60=0.35, snr=9.0, low_cut=120, high_cut=16000, ppm=12, drop=-4),
    "50cm": dict(distance=0.50, rt60=0.40, snr=7.0, low_cut=150, high_cut=14000, ppm=20, drop=-7),
    "1m": dict(distance=1.00, rt60=0.50, snr=5.0, low_cut=200, high_cut=11000, ppm=40, drop=-12),
    "2m": dict(distance=2.00, rt60=0.70, snr=3.5, low_cut=250, high_cut=8000, ppm=70, drop=-18),
    "4m": dict(distance=4.00, rt60=0.95, snr=2.0, low_cut=300, high_cut=6000, ppm=100, drop=-24),
}


def simulate_channel(source, output, scenario: str = "50cm", seed: int = 0,
                     critical_distance: float = 1.2) -> str:
    """Approximate playing `source` through a speaker and recording it at a distance.

    A teaching model, not a prediction: speaker low cut, room reverb (a synthetic impulse
    response whose direct-to-reverberant ratio falls 6 dB per doubling of distance), effective
    noise, microphone high cut, clock drift, level drop and 16-bit quantisation. The noise level
    is calibrated to one real speaker and microphone at 10 cm and 50 cm; your hardware will
    differ, so always confirm with a real recording.
    """
    from scipy import signal as sps
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {list(SCENARIOS)}")
    p = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    x, sr = sf.read(str(source), always_2d=True)
    y = x.mean(axis=1)
    b, a = sps.butter(2, p["low_cut"] / (sr / 2), "high")
    y = sps.lfilter(b, a, y)
    n = int(sr * p["rt60"] * 1.2)
    t = np.arange(n) / sr
    tail = rng.standard_normal(n) * np.exp(-6.91 * t / p["rt60"])     # -60 dB at rt60
    tail[: int(0.004 * sr)] = 0.0
    drr_db = 20 * np.log10(critical_distance / p["distance"])
    h = tail * np.sqrt(10 ** (-drr_db / 10) / np.sum(tail ** 2))
    h[0] += 1.0
    y = sps.fftconvolve(y, h)[: len(y)]
    power = np.sqrt(np.mean(y ** 2)) + 1e-12
    y = y + rng.normal(0, power * 10 ** (-p["snr"] / 20), len(y))
    b, a = sps.butter(4, min(p["high_cut"], 0.45 * sr) / (sr / 2), "low")
    y = sps.lfilter(b, a, y)
    y = sps.resample(y, int(round(len(y) * (1 + p["ppm"] * 1e-6))))
    lead = rng.normal(0, power * 10 ** (-p["snr"] / 20), int(rng.uniform(0.3, 1.5) * sr))
    y = np.concatenate([lead, y])
    y = y / (np.max(np.abs(y)) + 1e-12) * 0.9 * 10 ** (p["drop"] / 20)
    sf.write(str(output), np.round(y * 32767) / 32767, sr, subtype="PCM_16")
    return str(output)


# ----------------------------------------------------------------------------- laptop speaker + mic
def list_audio_devices() -> None:
    """Print input and output devices. Pass a name fragment (e.g. "RODE") to the other functions."""
    import sounddevice as sd
    apis = [h["name"] for h in sd.query_hostapis()]
    for i, d in enumerate(sd.query_devices()):
        io = []
        if d["max_input_channels"]:
            io.append("mic")
        if d["max_output_channels"]:
            io.append("speaker")
        print(f"  {i:>3}  {'/'.join(io):<11} {apis[d['hostapi']]:<20} {d['name']}")
    print(f"  defaults (input, output): {sd.default.device}")


_HOSTAPI_PREFERENCE = ("Windows WASAPI", "Core Audio", "ALSA", "PulseAudio", "MME", "Windows DirectSound")


def _device(spec, kind: str):
    """Resolve None (system default), an index, or a name fragment such as "RODE" to a device index.

    Device numbers change when hardware is replugged, so a name is the reliable way to pick one.
    Windows lists every device once per audio system; WASAPI is preferred because it runs at the
    device's native rate.
    """
    import sounddevice as sd
    if spec is None or isinstance(spec, int):
        return spec
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    apis = [h["name"] for h in sd.query_hostapis()]
    hits = [(i, d) for i, d in enumerate(sd.query_devices())
            if str(spec).lower() in d["name"].lower() and d[key] > 0]
    if not hits:
        raise ValueError(f"no {kind} device matching '{spec}'. Run list_audio_devices() to see them - "
                         f"if it is missing, the device is unplugged or in use.")
    rank = {name: n for n, name in enumerate(_HOSTAPI_PREFERENCE)}
    return min(hits, key=lambda h: rank.get(apis[h[1]["hostapi"]], 99))[0]


def _resample(x, sr_from: int, sr_to: int) -> np.ndarray:
    x = np.asarray(x, np.float32)
    if int(sr_from) == int(sr_to):
        return x
    from math import gcd
    from scipy.signal import resample_poly
    g = gcd(int(sr_from), int(sr_to))
    return resample_poly(x, int(sr_to) // g, int(sr_from) // g).astype(np.float32)


def _record_while(play_fn, seconds: float, in_device) -> tuple:
    """Record the input device while play_fn() runs; return (recording, sample rate, overruns).

    Records at the device's own rate and channel count (downmixed to mono): WASAPI refuses any
    other rate, and asking a stereo microphone for one channel halved its rate during testing.
    """
    import queue
    import threading
    import time
    import sounddevice as sd
    info = sd.query_devices(in_device, "input")
    nch, sr = int(info["max_input_channels"]), int(info["default_samplerate"])
    q, stop, over = queue.Queue(), threading.Event(), [0]

    def rec():
        need, got = int(seconds * sr), 0
        with sd.InputStream(samplerate=sr, channels=nch, device=in_device, dtype="float32",
                            blocksize=2048) as s:
            while got < need and not stop.is_set():
                d, o = s.read(2048)
                over[0] += int(bool(o))
                q.put(d.mean(axis=1))
                got += len(d)

    th = threading.Thread(target=rec, daemon=True)
    th.start()
    time.sleep(0.6)
    try:
        play_fn()
    finally:
        stop.set()
        th.join(timeout=5)
    chunks = []
    while not q.empty():
        chunks.append(q.get())
    return (np.concatenate(chunks) if chunks else np.zeros(0, np.float32)), sr, over[0]


def _play(data, sr: int, out_device) -> None:
    """Play mono `data` (at rate `sr`) through the output device at the device's own rate and
    channel count. WASAPI refuses any other rate, and a mono buffer on a stereo device is what
    corrupted playback during testing. Never louder than `data`."""
    import time
    import sounddevice as sd
    info = sd.query_devices(out_device, "output")
    out_sr = int(info["default_samplerate"])
    nch = max(1, min(2, int(info["max_output_channels"])))
    mono = np.clip(_resample(data, sr, out_sr), -1.0, 1.0)
    sd.play(np.repeat(mono.reshape(-1, 1), nch, axis=1), out_sr, device=out_device)
    sd.wait()
    time.sleep(0.8)


def check_audio_loop(out_device=None, in_device=None, *, level: float = 0.2) -> bool:
    """Play a 3 s 1 kHz tone and record it. Run this before trusting any measurement.

    Devices: None = system default, or a name fragment such as "RODE" (see list_audio_devices()).
    """
    import sounddevice as sd
    from scipy import signal as sps
    out_device, in_device = _device(out_device, "output"), _device(in_device, "input")
    sr = int(sd.query_devices(out_device, "output")["default_samplerate"])
    t = np.arange(int(3 * sr)) / sr
    fade = np.minimum(1, np.minimum(t / 0.05, (3 - t) / 0.05))
    tone = min(level, 0.5) * np.sin(2 * np.pi * 1000 * t) * fade
    rec, rec_sr, over = _record_while(lambda: _play(tone, sr, out_device), 5.0, in_device)
    if len(rec) < 16384:
        print("loop test: nothing was recorded")
        print("  PROBLEM - check that the microphone is plugged in and not used by another program")
        return False
    f, P = sps.welch(rec, rec_sr, nperseg=16384)
    peak = f[np.argmax(P)]
    share = P[(f > 960) & (f < 1040)].sum() / (P.sum() + 1e-20)
    level_db = 20 * np.log10(np.sqrt(np.mean(rec ** 2)) + 1e-12)
    ok = bool(abs(peak - 1000) < 15 and share > 0.5 and over == 0)
    print(f"loop test: loudest frequency {peak:.0f} Hz (expect 1000), tone share {share:.0%}, "
          f"level {level_db:.0f} dBFS, input overruns {over}")
    print("  OK - playback and recording look clean" if ok else
          "  PROBLEM - check devices and volume, and that no other program is using the audio device")
    return ok


def play_and_record(source, output, out_device=None, in_device=None, gain: float = 1.0) -> str:
    """Play `source` on the speaker while recording the microphone; save as `output` (WAV).

    Devices: None = system default, or a name fragment such as "RODE" (see list_audio_devices()).
    `gain` below 1 plays quieter; the file is never amplified (set the volume on the speaker).
    The recording is saved at the microphone's own sample rate; the decoder accepts any rate.
    """
    out_device, in_device = _device(out_device, "output"), _device(in_device, "input")
    x, sr = sf.read(str(source), always_2d=True)
    y = x.mean(axis=1) * min(gain, 1.0)
    rec, rec_sr, over = _record_while(lambda: _play(y, sr, out_device), len(y) / sr + 2.0, in_device)
    sf.write(str(output), rec, rec_sr, subtype="PCM_16")
    peak = float(np.max(np.abs(rec), initial=0))
    print(f"recorded {len(rec) / rec_sr:.1f} s -> {output}  (peak {peak:.2f}, input overruns {over})")
    if over:
        print("  warning: input overruns - samples were lost, record again")
    if peak >= 0.99:
        print("  warning: the recording clipped - lower the volume")
    return str(output)
