"""PNG のスキャンラインフィルタ。可逆な「予測層」の代表例。

PNG が GIF に勝つ理由の大半はここ。DEFLATE 自体は普通の汎用圧縮で、
画素を隣接予測の残差に変えてから渡すことでバイト分布を 0 付近に寄せている。
JPEG-LS の LOCO-I、FLAC の LPC、H.264 のイントラ予測と発想は同じ。
"""

NONE, SUB, UP, AVERAGE, PAETH = range(5)


def paeth(a, b, c):
    """左 a・上 b・左上 c のうち、線形予測 a+b-c に最も近いものを採る。"""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _filter_row(ftype, row, prev, bpp):
    out = bytearray(len(row))
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if ftype == NONE:
            p = 0
        elif ftype == SUB:
            p = a
        elif ftype == UP:
            p = b
        elif ftype == AVERAGE:
            p = (a + b) // 2
        else:
            p = paeth(a, b, c)
        out[i] = (x - p) & 0xFF
    return out


def _unfilter_row(ftype, row, prev, bpp):
    out = bytearray(len(row))
    for i, x in enumerate(row):
        a = out[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if ftype == NONE:
            p = 0
        elif ftype == SUB:
            p = a
        elif ftype == UP:
            p = b
        elif ftype == AVERAGE:
            p = (a + b) // 2
        else:
            p = paeth(a, b, c)
        out[i] = (x + p) & 0xFF
    return out


def _cost(filtered):
    """libpng の minimum sum of absolute differences ヒューリスティック。

    残差を符号付きとみなした絶対値の和が小さいほど、後段の DEFLATE で
    縮みやすい。実際に圧縮して比べるより桁違いに速く、ほぼ同じ選択になる。
    """
    return sum(v if v < 128 else 256 - v for v in filtered)


def filter_image(raw, width, height, bpp):
    """各行の先頭にフィルタ種別バイトを付けた bytes を返す。"""
    stride = width * bpp
    prev = bytes(stride)
    out = bytearray()
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        candidates = [_filter_row(f, row, prev, bpp) for f in range(5)]
        ftype = min(range(5), key=lambda f: _cost(candidates[f]))
        out.append(ftype)
        out += candidates[ftype]
        prev = row
    return bytes(out)


def unfilter_image(data, width, height, bpp):
    stride = width * bpp
    prev = bytes(stride)
    out = bytearray()
    pos = 0
    for _ in range(height):
        ftype = data[pos]
        row = data[pos + 1 : pos + 1 + stride]
        pos += 1 + stride
        restored = _unfilter_row(ftype, row, prev, bpp)
        out += restored
        prev = restored
    return bytes(out)
