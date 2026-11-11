"""Audio of the annotated file, as the view needs it."""

import numpy as np
import soundfile as sf

SAMPLING_RATE = 16000


def load_signal(path: str) -> np.ndarray:
    """Mono float32 signal at 16 kHz."""
    import audresample

    signal, sr = sf.read(path, dtype="float32", always_2d=True)
    signal = signal.mean(axis=1)
    if sr != SAMPLING_RATE:
        signal = audresample.resample(signal, sr, SAMPLING_RATE)[0]
    return signal.astype(np.float32)


def envelope(signal: np.ndarray, sampling_rate: int, rate: int) -> np.ndarray:
    """Min / max per bin of ``sampling_rate / rate`` samples as int8, interleaved ``[min0, max0, ...]``.

    Scaled to the loudest sample so quiet recordings are still visible.
    """
    hop = max(sampling_rate // rate, 1)
    n = int(np.ceil(len(signal) / hop))
    padded = np.zeros(n * hop, dtype=np.float32)
    padded[: len(signal)] = signal
    frames = padded.reshape(n, hop)
    scale = 127 / max(float(np.abs(signal).max(initial=0.0)), 1e-6)
    out = np.empty(2 * n, dtype=np.int8)
    out[0::2] = np.clip(np.round(frames.min(axis=1) * scale), -127, 127)
    out[1::2] = np.clip(np.round(frames.max(axis=1) * scale), -127, 127)
    return out
