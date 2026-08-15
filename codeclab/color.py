"""色空間変換とクロマサブサンプリング。JPEG / MPEG / H.26x の前処理。

「損失を減らす」議論でいちばん効く層。人間の視覚は輝度の空間解像度に比べて
色差の解像度が数分の一しかないので、Cb/Cr を 1/2 に間引いても
ほとんど気づかれない — 認知の穴を最初に突くのがここ。

ycocg_r は可逆版。H.264 の可逆モードと JPEG XL が使う。
"""

# JPEG/JFIF は BT.601 のフルレンジ
KR, KG, KB = 0.299, 0.587, 0.114


def rgb_to_ycbcr(r, g, b):
    y = KR * r + KG * g + KB * b
    return y, 128 + (b - y) * 0.5 / (1 - KB), 128 + (r - y) * 0.5 / (1 - KR)


def ycbcr_to_rgb(y, cb, cr):
    r = y + (cr - 128) * 2 * (1 - KR)
    b = y + (cb - 128) * 2 * (1 - KB)
    g = (y - KR * r - KB * b) / KG
    return r, g, b


def ycocg_r(r, g, b):
    """可逆な色変換。整数のまま往復できるのでロスレス圧縮に使える。"""
    co = r - b
    t = b + (co >> 1)
    cg = g - t
    y = t + (cg >> 1)
    return y, co, cg


def ycocg_r_inv(y, co, cg):
    t = y - (cg >> 1)
    g = cg + t
    b = t - (co >> 1)
    return b + co, g, b


def subsample_420(plane, width, height):
    """2x2 平均で 1/4 に間引く。JPEG の 4:2:0 と同じ。幅・高さは偶数前提。"""
    w2, h2 = width // 2, height // 2
    return [
        (
            plane[2 * y * width + 2 * x]
            + plane[2 * y * width + 2 * x + 1]
            + plane[(2 * y + 1) * width + 2 * x]
            + plane[(2 * y + 1) * width + 2 * x + 1]
        )
        / 4
        for y in range(h2)
        for x in range(w2)
    ]


def upsample_420(plane, width, height):
    """最近傍で戻す。実装によっては双線形だが、差が出るのは輪郭だけ。"""
    w2 = width // 2
    return [plane[(y // 2) * w2 + (x // 2)] for y in range(height) for x in range(width)]
