"""MDCT (Modified DCT)。MP3 / AAC / Vorbis / Opus / AC-3 の変換層。

2N サンプルから N 係数しか出さないのに、隣接フレームの重ね合わせで
完全再構成できる(TDAC: Time-Domain Alias Cancellation)。
ブロック境界の不連続がそのまま可聴ノイズになる音声で、
窓を重ねながら係数を増やさずに済むのがこの変換の価値。

窓は Princen-Bradley 条件 w[n]^2 + w[n+N]^2 = 1 を満たす必要がある。
"""

import math


def sine_window(n2):
    """MP3 / AAC のサイン窓。Princen-Bradley 条件を満たす。"""
    return [math.sin(math.pi / n2 * (i + 0.5)) for i in range(n2)]


def kbd_placeholder(n2):
    """AAC が長ブロックで使う KBD 窓は未実装。ROADMAP 参照。"""
    raise NotImplementedError("KBD window")


def mdct(x):
    """長さ 2N の窓掛け済みフレーム -> N 係数。"""
    n2 = len(x)
    n = n2 // 2
    n0 = (n + 1) / 2
    return [
        sum(x[k] * math.cos(math.pi / n * (k + n0) * (i + 0.5)) for k in range(n2))
        for i in range(n)
    ]


def imdct(spec):
    """N 係数 -> 長さ 2N。単体では時間領域エイリアスを含む。"""
    n = len(spec)
    n2 = n * 2
    n0 = (n + 1) / 2
    return [
        (2 / n)
        * sum(spec[i] * math.cos(math.pi / n * (k + n0) * (i + 0.5)) for i in range(n))
        for k in range(n2)
    ]


def analyze(signal, n, window=None):
    """N ホップ・2N 窓でフレーム分割し、係数列を返す。"""
    w = window or sine_window(2 * n)
    frames = []
    padded = [0.0] * n + list(signal) + [0.0] * (2 * n)
    for start in range(0, len(padded) - 2 * n + 1, n):
        frame = [padded[start + i] * w[i] for i in range(2 * n)]
        frames.append(mdct(frame))
    return frames


def synthesize(frames, n, length, window=None):
    """analyze の逆。重ね合わせでエイリアスが打ち消える。"""
    w = window or sine_window(2 * n)
    out = [0.0] * (n * (len(frames) + 1) + n)
    for f, spec in enumerate(frames):
        block = imdct(spec)
        base = f * n
        for i in range(2 * n):
            out[base + i] += block[i] * w[i]
    return out[n : n + length]
