"""保持音高: sound played faster or slower at its own pitch, a piece at a time (the preview's
播放速度, ui/player.py).

WSOLA (waveform-similarity overlap-add): the output is made of N-sample frames of the input,
Hann-windowed and overlapped by half (the windows add up to 1). The frames are taken
rate x HS apart in the input, so the sound is that much shorter or longer, but each one may
move up to TOL samples from there to where it best matches how the last one went on (the
cross-correlation's peak), so the waves join without the warble of a plain overlap-add.

Stretch.feed takes the sound as it comes and gives back exactly as much as it should last
(len / rate, the leftover fractions carried as speed_pcm does); the first frame needs a
little sound ahead, so the very start comes out as a few ms of silence (a constant delay).
"""
import numpy as np

N = 1024                     # frame (21 ms at 48 kHz)
HS = N // 2                  # output hop
TOL = 256                    # how far a frame may move to match the last one
FFT = 2048                   # >= N + 2 TOL: the correlation's lags without wrapping round
WIN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)).astype(np.float32)[:, None]   # periodic Hann


def best_lag(region, template):
    """Where in region template fits best (0 .. len(region) - len(template))."""
    c = np.fft.irfft(np.fft.rfft(region, FFT) * np.conj(np.fft.rfft(template, FFT)), FFT)
    return int(np.argmax(c[:len(region) - len(template) + 1]))


class Stretch:
    def __init__(self, rate, channels):
        self.rate, self.ch = float(rate), channels
        self.buf = np.zeros((0, channels), np.float32)      # input still to be looked at
        self.pos = 0.0                                      # where the next frame would start in buf
        self.last = None                                    # where the last frame started in buf
        self.acc = np.zeros((N, channels), np.float32)      # overlap-add of frames not yet given out
        self.ready = []                                     # finished output pieces
        self.n_ready = 0

    def _frame(self):
        """Add one frame (False: not enough input for it yet)."""
        nom = int(round(self.pos))
        if self.last is None:
            c = nom
            if len(self.buf) < c + N:
                return False
        else:
            nat = self.last + HS                            # how the last frame went on
            lo, hi = max(0, nom - TOL), nom + TOL
            if len(self.buf) < max(hi, nat) + N:
                return False
            region = self.buf[lo:hi + N].mean(axis=1)
            c = lo + best_lag(region, self.buf[nat:nat + N].mean(axis=1))
        self.acc += self.buf[c:c + N] * WIN
        self.ready.append(self.acc[:HS].copy())
        self.n_ready += HS
        self.acc = np.concatenate([self.acc[HS:], np.zeros((HS, self.ch), np.float32)])
        self.last = c
        self.pos += HS * self.rate
        drop = min(int(self.pos) - TOL, self.last + HS)    # (input nothing looks at again)
        if drop > 0:
            self.buf = self.buf[drop:]
            self.pos -= drop
            self.last -= drop
        return True

    def feed(self, pcm, carry=0.0):
        """Interleaved int16 sound in; (the same played rate times as fast at its own pitch,
        the fraction of a sample left over)."""
        a = np.frombuffer(pcm, np.int16).reshape(-1, self.ch).astype(np.float32)
        self.buf = np.concatenate([self.buf, a]) if len(self.buf) else a
        want = len(a) / self.rate + carry
        n = int(want)
        while self.n_ready < n and self._frame():
            pass
        got = np.concatenate(self.ready) if self.ready else np.zeros((0, self.ch), np.float32)
        out, rest = got[:n], got[n:]
        self.ready, self.n_ready = ([rest], len(rest)) if len(rest) else ([], 0)
        if len(out) < n:                                    # (the start: silence until a frame is ready)
            out = np.concatenate([np.zeros((n - len(out), self.ch), np.float32), out])
        return np.clip(np.round(out), -32768, 32767).astype(np.int16).tobytes(), want - n
