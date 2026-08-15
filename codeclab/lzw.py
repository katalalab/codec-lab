"""LZW。GIF・TIFF・PDF(LZWDecode)・旧 UNIX compress。

辞書を明示的に送らず、復号側が同じ規則で同じ辞書を組み立てる。
落とし穴は「復号側は 1 エントリ遅れる」こと。符号幅を増やす瞬間が
符号化側と 1 コードずれるので、幅拡張の条件が両側で 1 だけ違う。
"""

from .bits import BitReader, BitWriter

CLEAR = 256
END = 257
FIRST = 258


def encode(data, max_bits=12):
    w = BitWriter()
    table = {bytes([i]): i for i in range(256)}
    nxt, width = FIRST, 9
    w.write(CLEAR, width)

    cur = b""
    for b in data:
        nc = cur + bytes([b])
        if nc in table:
            cur = nc
            continue
        w.write(table[cur], width)
        if nxt < (1 << max_bits):
            table[nc] = nxt
            nxt += 1
            if nxt == (1 << width) and width < max_bits:
                width += 1
        else:
            w.write(CLEAR, width)
            table = {bytes([i]): i for i in range(256)}
            nxt, width = FIRST, 9
        cur = bytes([b])

    if cur:
        w.write(table[cur], width)
        # 復号側は最後のコードを読んだ後にもう 1 エントリ足す。そこで幅が
        # 上がるケースがあるので、END を書く前に同じ判定を通しておく
        if nxt + 1 == (1 << width) and width < max_bits:
            width += 1
    w.write(END, width)
    return w.bytes()


def decode(blob, max_bits=12):
    r = BitReader(blob)
    table = {i: bytes([i]) for i in range(256)}
    nxt, width = FIRST, 9
    prev = None
    out = bytearray()

    while True:
        code = r.read(width)
        if code == END:
            return bytes(out)
        if code == CLEAR:
            table = {i: bytes([i]) for i in range(256)}
            nxt, width = FIRST, 9
            prev = None
            continue

        if code in table:
            entry = table[code]
        elif code == nxt and prev is not None:
            # KwKwK ケース: 符号化側が今まさに作ったエントリを即使っている
            entry = prev + prev[:1]
        else:
            raise ValueError(f"未定義のコード {code}")

        out += entry
        if prev is not None and nxt < (1 << max_bits):
            table[nxt] = prev + entry[:1]
            nxt += 1
            # 符号化側より 1 エントリ遅れているぶん、拡張条件を 1 早める
            if nxt + 1 == (1 << width) and width < max_bits:
                width += 1
        prev = entry
