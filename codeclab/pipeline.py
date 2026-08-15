"""層を合成した「実物に対応するコーデック」。単層では出ない圧縮率はここで出る。

  png_like    予測(PNG フィルタ) → 辞書+符号化(DEFLATE)      = PNG そのもの
  ycocg_png   変換(YCoCg-R) → 予測 → DEFLATE                  = PNG + 可逆色変換
              (H.264 可逆 / JPEG XL / WebP lossless のプレーン分離構成)
  png_rans    予測 → 符号化(rANS)                             = 辞書層を抜いた PNG
  flac_like   予測(LPC) → 符号化(Rice)                        = FLAC の最小構成

汎用コーデックとの違いは「素材の形を知っている」こと。画像なら幅・高さ・bpp、
音声なら int16 LE という前提を使って、生バイト列では見えない相関を先に落とす。
"""

from functools import partial

from . import color, deflate, lpc, png_filter, rans

# 復号側は圧縮結果しか受け取らないので、PNG の IHDR に相当する形の情報を先頭に置く
GEOM_HEADER = 5


def _pack_geom(width, height, bpp):
    return width.to_bytes(2, "big") + height.to_bytes(2, "big") + bytes([bpp])


def _unpack_geom(blob):
    return int.from_bytes(blob[:2], "big"), int.from_bytes(blob[2:4], "big"), blob[4]


def png_like(raw, width, height, bpp):
    filtered = png_filter.filter_image(raw, width, height, bpp)
    return _pack_geom(width, height, bpp) + deflate.encode(filtered)


def png_like_decode(blob):
    width, height, bpp = _unpack_geom(blob)
    return png_filter.unfilter_image(deflate.decode(blob[GEOM_HEADER:]), width, height, bpp)


def png_rans(raw, width, height, bpp):
    filtered = png_filter.filter_image(raw, width, height, bpp)
    return _pack_geom(width, height, bpp) + rans.encode(filtered)


def png_rans_decode(blob):
    width, height, bpp = _unpack_geom(blob)
    return png_filter.unfilter_image(rans.decode(blob[GEOM_HEADER:]), width, height, bpp)


def _ycocg_planes(raw):
    """RGB8 -> YCoCg-R の 4 プレーン。Co/Cg は 9bit に広がるので符号だけ 4 枚目へ。

    PNG のようにインターリーブせずプレーンに分けるのは、色変換後の 3 面が
    統計的に別物になるから。行ごとに 1 種類しか選べないフィルタを共有させると
    どの面にも中途半端にしか効かない。RGB のままなら 3 面が似ているので
    分離は逆効果になる — 分離が効くのは色変換を先に通したからで、順序が要点。
    """
    n = len(raw) // 3
    planes = (bytearray(n), bytearray(n), bytearray(n), bytearray(n))
    for p in range(n):
        y, co, cg = color.ycocg_r(raw[3 * p], raw[3 * p + 1], raw[3 * p + 2])
        planes[0][p] = y
        planes[1][p] = co & 0xFF
        planes[2][p] = cg & 0xFF
        planes[3][p] = (co < 0) + 2 * (cg < 0)
    return planes


def ycocg_png(raw, width, height):
    filtered = b"".join(
        png_filter.filter_image(bytes(p), width, height, 1) for p in _ycocg_planes(raw)
    )
    return _pack_geom(width, height, 1) + deflate.encode(filtered)


def ycocg_png_decode(blob):
    width, height, bpp = _unpack_geom(blob)
    filtered = deflate.decode(blob[GEOM_HEADER:])
    step = height * (width * bpp + 1)
    planes = [
        png_filter.unfilter_image(filtered[i * step : (i + 1) * step], width, height, bpp)
        for i in range(4)
    ]
    out = bytearray()
    for p in range(width * height):
        sign = planes[3][p]
        out += bytes(
            color.ycocg_r_inv(
                planes[0][p],
                planes[1][p] - 256 * (sign & 1),
                planes[2][p] - 256 * (sign >> 1),
            )
        )
    return bytes(out)


def flac_like(data):
    samples = [
        int.from_bytes(data[i : i + 2], "little", signed=True)
        for i in range(0, len(data), 2)
    ]
    return lpc.encode(samples)


def flac_like_decode(blob):
    return b"".join((s & 0xFFFF).to_bytes(2, "little") for s in lpc.decode(blob))


def image_codecs(width, height, bpp):
    """幅・高さ・bpp を束ねて bytes -> bytes にした画像用の合成コーデック。"""
    return {
        "png_like": (partial(png_like, width=width, height=height, bpp=bpp), png_like_decode),
        "ycocg_png": (partial(ycocg_png, width=width, height=height), ycocg_png_decode),
        "png_rans": (partial(png_rans, width=width, height=height, bpp=bpp), png_rans_decode),
    }


def audio_codecs():
    return {"flac_like": (flac_like, flac_like_decode)}
