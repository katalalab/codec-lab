"""線形予測。FLAC / ALAC / Shorten / WavPack の心臓部。

x[n] を過去のサンプルの線形結合で予測し、残差だけを Rice 符号で書く。
可逆でいられるのは、係数を整数に量子化してシフトで割り、予測値を
整数で確定させているから。浮動小数のまま使うと復元が一致しなくなる。
"""

from .bits import BitReader, BitWriter
from . import rice

# FLAC の固定予測器。次数 = 何階差分を取るかに対応する
FIXED = {
    0: [],
    1: [1],
    2: [2, -1],
    3: [3, -3, 1],
    4: [4, -6, 4, -1],
}


def autocorrelation(x, order):
    return [sum(x[i] * x[i - lag] for i in range(lag, len(x))) for lag in range(order + 1)]


def levinson(r, order):
    """Levinson-Durbin。自己相関から最小二乗の予測係数を O(order^2) で解く。"""
    a = [0.0] * order
    err = r[0]
    if err == 0:
        return a
    for i in range(order):
        acc = r[i + 1] - sum(a[j] * r[i - j] for j in range(i))
        k = acc / err
        prev = a[:i]
        a[i] = k
        for j in range(i):
            a[j] = prev[j] - k * prev[i - 1 - j]
        err *= 1 - k * k
        if err <= 0:
            break
    return a


def quantize(coeffs, precision=15):
    """係数を整数 + 右シフト量にする。ここを整数化しないと可逆にならない。"""
    if not coeffs:
        return [], 0
    peak = max(abs(c) for c in coeffs) or 1e-9
    shift = precision - 1 - max(0, int(peak).bit_length())
    shift = max(0, min(15, shift))
    limit = (1 << (precision - 1)) - 1
    q = [max(-limit - 1, min(limit, round(c * (1 << shift)))) for c in coeffs]
    return q, shift


def predict(x, i, q, shift):
    return sum(q[j] * x[i - 1 - j] for j in range(len(q))) >> shift


def residual(x, q, shift):
    order = len(q)
    return [x[i] - predict(x, i, q, shift) for i in range(order, len(x))]


def restore(warmup, res, q, shift):
    x = list(warmup)
    for e in res:
        x.append(e + predict(x, len(x), q, shift))
    return x


def encode(samples, order=8, precision=15):
    """int の列 -> bytes。固定予測器と LPC を全部試して最小を選ぶ。"""
    n = len(samples)
    if n == 0:
        return (0).to_bytes(4, "big")

    best = None
    for q, shift in _candidates(samples, order, precision):
        if len(q) >= n:
            continue
        res = residual(samples, q, shift)
        k = rice.best_k(res)
        cost = sum((rice.zigzag(v) >> k) + 1 + k for v in res)
        if best is None or cost < best[0]:
            best = (cost, q, shift, res, k)

    _, q, shift, res, k = best
    order_used = len(q)
    w = BitWriter()
    w.write(order_used, 5)
    w.write(shift, 4)
    w.write(k, 5)
    for c in q:
        w.write(c & 0xFFFF, 16)
    for s in samples[:order_used]:
        w.write(rice.zigzag(s), 32)
    rice.write(w, res, k)
    return n.to_bytes(4, "big") + w.bytes()


def _candidates(samples, order, precision):
    for coeffs in FIXED.values():
        yield coeffs, 0
    if len(samples) > order * 2:
        yield quantize(levinson(autocorrelation(samples, order), order), precision)


def decode(blob):
    n = int.from_bytes(blob[:4], "big")
    if n == 0:
        return []
    r = BitReader(blob[4:])
    order = r.read(5)
    shift = r.read(4)
    k = r.read(5)
    q = []
    for _ in range(order):
        v = r.read(16)
        q.append(v - 65536 if v & 0x8000 else v)
    warmup = [rice.unzigzag(r.read(32)) for _ in range(order)]
    res = rice.read(r, n - order, k)
    return restore(warmup, res, q, shift)
