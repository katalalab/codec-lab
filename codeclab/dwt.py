"""ウェーブレット変換。JPEG2000 / JPEG XL(Squeeze) / Dirac の変換層。

DCT がブロック単位で「ブロックノイズ」を出すのに対し、DWT は画像全体を
多重解像度に分けるのでブロック境界が出ない。代わりに低ビットレートでは
リンギングが出る — 破綻の仕方が違うだけで、どちらも認知の穴を突いている。

cdf53 はリフティング実装で整数のまま完全可逆。JPEG2000 の可逆モードと
同じ変換で、「可逆と非可逆を同じ変換で切り替える」設計の実例。
"""


def haar(x):
    """最も単純な直交ウェーブレット。(平均, 差分) に分ける。可逆。"""
    n = len(x) // 2
    lo = [(x[2 * i] + x[2 * i + 1]) >> 1 for i in range(n)]
    hi = [x[2 * i] - x[2 * i + 1] for i in range(n)]
    return lo, hi


def ihaar(lo, hi):
    out = []
    for l, h in zip(lo, hi):
        # (a+b)>>1 で落ちた最下位ビットは差分の偶奇から復元できる
        a = l + ((h + (h & 1)) >> 1)
        out += [a, a - h]
    return out


def _ext(x, i):
    """対称拡張。境界で信号を折り返す(JPEG2000 と同じ扱い)。"""
    n = len(x)
    if i < 0:
        i = -i
    if i >= n:
        i = 2 * (n - 1) - i
    return x[i]


def cdf53(x):
    """CDF 5/3 整数リフティング。JPEG2000 可逆モード。長さは偶数。"""
    n = len(x) // 2
    d = [_ext(x, 2 * i + 1) - ((_ext(x, 2 * i) + _ext(x, 2 * i + 2)) >> 1) for i in range(n)]
    s = [
        _ext(x, 2 * i) + (((d[i - 1] if i > 0 else d[0]) + d[i] + 2) >> 2)
        for i in range(n)
    ]
    return s, d


def icdf53(s, d):
    n = len(s)
    x = [0] * (2 * n)
    for i in range(n):
        x[2 * i] = s[i] - (((d[i - 1] if i > 0 else d[0]) + d[i] + 2) >> 2)
    for i in range(n):
        a = x[2 * i]
        b = x[2 * i + 2] if i + 1 < n else x[2 * i]
        x[2 * i + 1] = d[i] + ((a + b) >> 1)
    return x
