"""DCT-II / DCT-III(逆)。JPEG・MPEG・H.26x の変換層。

自然画像の隣接画素は強く相関しているので、周波数へ移すとエネルギーが
低周波に偏る。「情報を捨てる」のは DCT ではなく次の量子化段で、
DCT 自体は正規直交なので理屈上ロスレス(浮動小数の丸め誤差のみ)。

ponytail: O(N^2) の素朴実装。JPEG 実装が使う AAN や整数 DCT
(H.264 の 4x4 は乗算だけで閉じる)へ差し替える余地がある。
"""

import math

N = 8

_COS = [
    [math.cos((2 * x + 1) * u * math.pi / (2 * N)) for x in range(N)]
    for u in range(N)
]
_ALPHA = [math.sqrt(1 / N)] + [math.sqrt(2 / N)] * (N - 1)


def dct_1d(v):
    return [_ALPHA[u] * sum(v[x] * _COS[u][x] for x in range(N)) for u in range(N)]


def idct_1d(c):
    return [sum(_ALPHA[u] * c[u] * _COS[u][x] for u in range(N)) for x in range(N)]


def _transpose(m):
    return [list(row) for row in zip(*m)]


def dct_2d(block):
    """8x8 の 2 次元 DCT。行→列の分離実装(2D を 2 回の 1D に分ける)。"""
    rows = [dct_1d(row) for row in block]
    return _transpose([dct_1d(col) for col in _transpose(rows)])


def idct_2d(block):
    rows = [idct_1d(row) for row in block]
    return _transpose([idct_1d(col) for col in _transpose(rows)])
