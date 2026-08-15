"""Rice/Golomb 符号。FLAC・Shorten・ALAC・一部の可逆画像がこれ。

商を unary、剰余を k bit で書くだけ。予測残差はラプラス分布に近いので、
テーブルを持たずにハフマンとほぼ同等の圧縮率が出る。FLAC が
「予測 → 残差 → Rice」で完結しているのはこの性質のおかげ。
"""


def zigzag(v):
    """符号付きを非負へ折り返す。0,-1,1,-2,2 -> 0,1,2,3,4"""
    return (v << 1) if v >= 0 else ((-v << 1) - 1)


def unzigzag(u):
    return (u >> 1) if u % 2 == 0 else -((u + 1) >> 1)


def best_k(values):
    """総ビット数が最小になる k を総当たりで選ぶ。

    FLAC は分割ごとに同じことをする(ただし平均から推定して探索を狭める)。
    ponytail: O(31n) の総当たり。パーティション分割を入れるときに近似へ落とす。
    """
    if not values:
        return 0
    us = [zigzag(v) for v in values]
    return min(range(31), key=lambda k: sum((u >> k) + 1 + k for u in us))


def write(w, values, k):
    mask = (1 << k) - 1
    for v in values:
        u = zigzag(v)
        for _ in range(u >> k):
            w.bit(1)
        w.bit(0)
        if k:
            w.write(u & mask, k)


def read(r, count, k):
    out = []
    for _ in range(count):
        q = 0
        while r.bit():
            q += 1
        out.append(unzigzag((q << k) | (r.read(k) if k else 0)))
    return out
