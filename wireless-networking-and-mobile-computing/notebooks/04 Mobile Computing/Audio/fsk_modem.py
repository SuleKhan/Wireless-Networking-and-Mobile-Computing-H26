"""A small acoustic modem for Assignment 08, Step 5 (notebook Audio_Modem.ipynb).

A transmission is bracketed by two chirps:

    [ silence ][ up-chirp ][ gap ][ payload, 4-FSK ][ gap ][ down-chirp ][ silence ]

The chirps are known signals, so the receiver finds them by correlation even in noise, and the
payload is whatever lies between them. The payload is 4-FSK: one of four tones per symbol, two
bits per symbol. Text is ASCII, one byte per character, most significant bit first.

This module is the transmitter and the plumbing. The detector - deciding which tone was sent in
each symbol - is yours to write in the notebook; `decode_frame` and `self_test` take your two
functions as arguments.

Adapted from the acoustic workshop modem of the Mobile Computing course.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import numpy as np
import soundfile as sf

SAMPLE_RATE = 48_000
TONE_COUNT = 4                       # 4-FSK: two bits per symbol
SPACING_HZ = 200.0

LEAD_S, TAIL_S, GAP_S = 0.5, 0.5, 0.1
CHIRP_LOW_HZ, CHIRP_HIGH_HZ = 300.0, 3000.0
UP_CHIRP_S, DOWN_CHIRP_S = 0.5, 0.25
AMPLITUDE = 0.45
GUARD = 0.2                          # fraction of each symbol ignored at both edges


# ----------------------------------------------------------------------------- parameters
@dataclass
class ModemParameters:
    base_hz: float
    spacing_hz: float
    symbol_ms: float

    @property
    def tones_hz(self) -> np.ndarray:
        return self.base_hz + self.spacing_hz * np.arange(TONE_COUNT)

    @property
    def bit_rate(self) -> float:
        return 2 * 1000.0 / self.symbol_ms

    def __str__(self) -> str:
        tones = ", ".join(f"{f:.0f}" for f in self.tones_hz)
        return (f"tones {tones} Hz, symbol {self.symbol_ms:g} ms "
                f"-> {1000 / self.symbol_ms:.1f} symbols/s, {self.bit_rate:.1f} bit/s")


def my_parameters(legi: str) -> ModemParameters:
    """Your personal channel, from the last two digits of your matriculation number.

    base frequency = 800 Hz + 100 Hz x (last digit)                -> 800 ... 1700 Hz
    symbol length  = 30 ms  + 5 ms  x (second-last digit mod 7)    -> 30 ... 60 ms
    """
    digits = re.sub(r"\D", "", str(legi))
    if len(digits) < 2:
        raise ValueError("give your matriculation number, e.g. '21-123-456'")
    last, second = int(digits[-1]), int(digits[-2])
    return ModemParameters(base_hz=800.0 + 100.0 * last, spacing_hz=SPACING_HZ,
                           symbol_ms=30.0 + 5.0 * (second % 7))


# ----------------------------------------------------------------------------- bits and text
def text_to_bits(text: str) -> np.ndarray:
    data = np.frombuffer(text.encode("ascii", errors="replace"), dtype=np.uint8)
    return np.unpackbits(data)                       # most significant bit first


def bits_to_text(bits) -> str:
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    bits = bits[: len(bits) // 8 * 8]
    data = np.packbits(bits)
    return "".join(chr(b) if 32 <= b < 127 else "·" for b in data)


# ----------------------------------------------------------------------------- transmitter
def _fade(n: int, rate: int, seconds: float = 0.004) -> np.ndarray:
    edge = max(1, int(seconds * rate))
    i = np.arange(n)
    return np.minimum(1.0, np.minimum(i + 1, n - i) / edge)


def make_chirp(rate: int = SAMPLE_RATE, down: bool = False) -> np.ndarray:
    """A linear sweep 300 -> 3000 Hz (up, 0.5 s) or 3000 -> 300 Hz (down, 0.25 s)."""
    seconds = DOWN_CHIRP_S if down else UP_CHIRP_S
    n = int(round(seconds * rate))
    t = np.arange(n) / rate
    f0, f1 = (CHIRP_HIGH_HZ, CHIRP_LOW_HZ) if down else (CHIRP_LOW_HZ, CHIRP_HIGH_HZ)
    phase = 2 * np.pi * (f0 * t + 0.5 * (f1 - f0) / seconds * t ** 2)
    return AMPLITUDE * _fade(n, rate, 0.02) * np.sin(phase)


def samples_per_symbol(symbol_ms: float, rate: int) -> int:
    return int(round(rate * symbol_ms / 1000.0))


def modulate(bits, params: ModemParameters, rate: int = SAMPLE_RATE) -> np.ndarray:
    """Two bits per symbol: 00 -> tone 0 (lowest), 01 -> tone 1, 10 -> tone 2, 11 -> tone 3."""
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    symbols = bits[0::2] * 2 + bits[1::2]
    n = samples_per_symbol(params.symbol_ms, rate)
    t = np.arange(n) / rate
    bank = np.sin(2 * np.pi * np.outer(params.tones_hz, t)) * _fade(n, rate)
    return AMPLITUDE * bank[symbols].ravel()


def make_frame(text: str, params: ModemParameters, rate: int = SAMPLE_RATE) -> np.ndarray:
    """The complete transmission: silence, up-chirp, payload, down-chirp, silence."""
    gap = np.zeros(int(round(GAP_S * rate)))
    return np.concatenate([np.zeros(int(LEAD_S * rate)), make_chirp(rate), gap,
                           modulate(text_to_bits(text), params, rate),
                           gap, make_chirp(rate, down=True), np.zeros(int(TAIL_S * rate))])


def save_wav(path, samples, rate: int = SAMPLE_RATE) -> str:
    sf.write(str(path), np.asarray(samples, dtype=np.float32), rate, subtype="PCM_16")
    return str(path)


# ----------------------------------------------------------------------------- loading
def _ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def load_audio(path) -> tuple[np.ndarray, int]:
    """Any recording as mono float. Phone formats (.m4a, .aac) are converted with ffmpeg."""
    try:
        x, rate = sf.read(str(path), always_2d=True)
    except Exception:
        ff = _ffmpeg()
        if ff is None:
            raise ValueError(f"cannot read '{path}'. Convert it to .wav, or pip install imageio-ffmpeg")
        with tempfile.TemporaryDirectory() as d:
            wav = os.path.join(d, "x.wav")
            r = subprocess.run([ff, "-y", "-v", "error", "-i", str(path), wav],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise ValueError(f"ffmpeg could not convert '{path}': {r.stderr.strip()[:300]}")
            x, rate = sf.read(wav, always_2d=True)
    return x.mean(axis=1), rate


# ----------------------------------------------------------------------------- receiver plumbing
def _match(samples: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of `template` against every offset of `samples` (1.0 = perfect)."""
    n_out = len(samples) - len(template) + 1
    if n_out < 1:
        raise ValueError("the recording is shorter than a chirp")
    size = 1 << int(np.ceil(np.log2(len(samples) + len(template))))
    corr = np.fft.irfft(np.fft.rfft(samples, size) * np.fft.rfft(template[::-1], size),
                        size)[len(template) - 1: len(samples)]
    c = np.concatenate([[0.0], np.cumsum(samples ** 2)])
    energy = c[len(template):] - c[:n_out]
    typical = len(template) * float(np.mean(samples ** 2))
    return np.abs(corr) / np.sqrt(np.maximum(energy, 1e-3 * typical) * np.sum(template ** 2))


@dataclass
class Frame:
    up_sample: int
    down_sample: int
    start: int                 # first payload sample
    end: int                   # one past the last payload sample
    up_score: float
    down_score: float
    rate: int
    up_corr: np.ndarray
    down_corr: np.ndarray

    def __str__(self) -> str:
        r = self.rate
        return (f"up-chirp at {self.up_sample / r:.3f} s (match {self.up_score:.2f}), "
                f"down-chirp at {self.down_sample / r:.3f} s (match {self.down_score:.2f}), "
                f"payload {self.start / r:.3f} .. {self.end / r:.3f} s")


def find_frame(samples, rate: int) -> Frame:
    """Locate the transmission by correlating for the up-chirp, then for the down-chirp after it."""
    samples = np.asarray(samples, dtype=float).ravel()
    up, down = make_chirp(rate), make_chirp(rate, down=True)
    up_corr = _match(samples, up)
    up_at = int(np.argmax(up_corr))
    after = up_at + len(up)
    down_corr = _match(samples[after:], down)
    down_at = after + int(np.argmax(down_corr))
    gap = int(round(GAP_S * rate))
    return Frame(up_at, down_at, after + gap, down_at - gap, float(up_corr[up_at]),
                 float(down_corr[down_at - after]), rate, up_corr, down_corr)


def slice_symbols(samples, frame: Frame, params: ModemParameters) -> list:
    """Cut the payload into one array per symbol, keeping only the middle (edges are unreliable).

    The number of symbols is read from the gap between the chirps, and the symbol length is
    stretched to fit it exactly, which absorbs the small clock difference between speaker and
    microphone.
    """
    samples = np.asarray(samples, dtype=float).ravel()
    nominal = samples_per_symbol(params.symbol_ms, frame.rate)
    count = max(1, int(round((frame.end - frame.start) / nominal)))
    per = (frame.end - frame.start) / count
    guard = int(GUARD * per)
    return [samples[int(frame.start + k * per) + guard: int(frame.start + (k + 1) * per) - guard]
            for k in range(count)]


def decode_frame(samples, rate: int, params: ModemParameters, tone_energies, demodulate,
                 verbose: bool = True) -> str:
    """Find the frame, measure every symbol with YOUR `tone_energies`, decide with YOUR `demodulate`."""
    frame = find_frame(samples, rate)
    symbols = slice_symbols(samples, frame, params)
    energies = np.array([tone_energies(s, rate, params.tones_hz) for s in symbols], dtype=float)
    bits = np.asarray(demodulate(energies), dtype=np.uint8).ravel()
    text = bits_to_text(bits)
    if verbose:
        print(frame)
        print(f"{len(symbols)} symbols -> {len(bits)} bits -> '{text}'")
    return text


def self_test(tone_energies, demodulate) -> bool:
    """Decode three known frames (clean, noisy, different parameters). Prints PASS or FAIL."""
    rng = np.random.default_rng(0)
    cases = [("SELFTEST-123", ModemParameters(1000, SPACING_HZ, 40), 48_000, None),
             ("Hello WNMC!", ModemParameters(1500, SPACING_HZ, 30), 44_100, 0.05),
             ("21-987-654", ModemParameters(800, SPACING_HZ, 60), 48_000, 0.10)]
    ok = True
    for text, p, rate, noise in cases:
        x = make_frame(text, p, rate)
        if noise:
            x = x + noise * rng.standard_normal(len(x))
        got = decode_frame(x, rate, p, tone_energies, demodulate, verbose=False)
        passed = got == text
        ok &= passed
        print(f"{'PASS' if passed else 'FAIL'}  sent '{text}'  got '{got}'  ({p}, {rate} Hz"
              f"{', noise' if noise else ''})")
    print("All tests passed." if ok else "Not yet: check tone_energies and demodulate.")
    return ok


# ----------------------------------------------------------------------------- plotting
def plot_spectrogram(samples, rate: int, params: ModemParameters | None = None,
                     frame: Frame | None = None, max_hz: float = 4000, title: str = ""):
    """Spectrogram of a recording, with the expected tones and the found chirps marked."""
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram
    f, t, S = spectrogram(np.asarray(samples, dtype=float), fs=rate, nperseg=1024, noverlap=768)
    keep = f <= max_hz
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.pcolormesh(t, f[keep], 10 * np.log10(S[keep] + 1e-12), shading="auto", cmap="viridis")
    if params is not None:
        for tone in params.tones_hz:
            ax.axhline(tone, color="white", lw=0.6, ls="--", alpha=0.7)
    if frame is not None:
        for s in (frame.up_sample, frame.down_sample):
            ax.axvline(s / rate, color="red", lw=1)
    ax.set(xlabel="time (s)", ylabel="frequency (Hz)", title=title)
    plt.tight_layout()
    plt.show()
