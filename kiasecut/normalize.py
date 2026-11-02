"""標準化 (normalize): a clip's sound brought up or down so that its loudest sample reaches a
level - measured over the part of its source the clip plays (audiomix.Source.key: from
source_start_us for the clip's length times its speed, in its sound stream), so trimming the
clip measures it again. The gain multiplies 音量 (which stays as it is, keyframes and all),
in the preview (audiomix) and in the export (build).

clip["normalize"]: the peak to reach, in dBFS (TARGET_DB to start with); absent: off.
"""
import threading

import numpy as np

TARGET_DB = -1.0
MAX_GAIN = 100.0              # +40 dB at most: a near-silent clip is not blown up into its hiss

_peaks = {}                   # Source key -> peak (0 - 1)
_lock = threading.Lock()


def target(c):
    """The peak a clip is normalized to (dBFS), or None when it is not."""
    v = c.get("normalize")
    return None if v is None else float(v)


def gain_of(c, peak):
    """The factor that takes a clip whose loudest sample is peak (0 - 1) to its target."""
    t = target(c)
    if t is None or not peak or peak <= 1e-6:
        return 1.0
    return min(MAX_GAIN, 10 ** (t / 20) / peak)


def peak_of(pcm):
    return float(np.abs(pcm.astype(np.int32)).max()) / 32768 if len(pcm) else 0.0


def remember(key, pcm):
    """The mixer decoded key's range: its peak is known from now on."""
    peak(key, pcm)


def peak(key, pcm):
    """The peak of the decoded range key (pcm), worked out once - only over the clip's own
    length (the decode runs a little past it)."""
    with _lock:
        if key not in _peaks:
            from .audiomix import RATE
            _peaks[key] = peak_of(pcm[:round(key[2] / 1_000_000 * RATE)])
        return _peaks[key]


def gain(c, cache_dir):
    """The normalizing factor for clip c (1 when it is not normalized), decoding its range
    when the preview has not (the export of a clip never played)."""
    if target(c) is None or not c.get("media"):
        return 1.0
    from . import audiomix                               # (it imports build, which imports this)
    key = audiomix.key_of(c)
    with _lock:
        peak = _peaks.get(key)
    if peak is None:
        try:
            pcm, _offset = audiomix.decode(cache_dir, key)
        except Exception:                                # unreadable: left as it is
            return 1.0
        remember(key, pcm)
        peak = _peaks[key]
    return gain_of(c, peak)
