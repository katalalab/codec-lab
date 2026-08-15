"""DEFLATE。zip / gzip / png(IDAT) / HTTP gzip の本体。

構造は「LZ77 で辞書参照 → 残りをハフマン」の二段。長さと距離を
そのまま書かず、対数的にグループ分けした符号 + 追加ビットで表すのが要点。
長さ 3..258 が 29 コード、距離 1..32768 が 30 コードに畳まれる。

RFC 1951 と bit-exact ではない: ビット詰めの LSB/MSB 混在と、符号長符号の
長さ制限(7bit 上限)を省いている。ブロック分割もせず常に 1 ブロック。構造は同じ。
"""

from . import huffman, lz77
from .bits import BitReader, BitWriter

# RFC 1951 の長さ符号 257..285: (最小長, 追加ビット数)
LENGTH_CODES = [
    (3, 0), (4, 0), (5, 0), (6, 0), (7, 0), (8, 0), (9, 0), (10, 0),
    (11, 1), (13, 1), (15, 1), (17, 1),
    (19, 2), (23, 2), (27, 2), (31, 2),
    (35, 3), (43, 3), (51, 3), (59, 3),
    (67, 4), (83, 4), (99, 4), (115, 4),
    (131, 5), (163, 5), (195, 5), (227, 5),
    (258, 0),
]
# 距離符号 0..29
DIST_CODES = [
    (1, 0), (2, 0), (3, 0), (4, 0),
    (5, 1), (7, 1), (9, 2), (13, 2),
    (17, 3), (25, 3), (33, 4), (49, 4),
    (65, 5), (97, 5), (129, 6), (193, 6),
    (257, 7), (385, 7), (513, 8), (769, 8),
    (1025, 9), (1537, 9), (2049, 10), (3073, 10),
    (4097, 11), (6145, 11), (8193, 12), (12289, 12),
    (16385, 13), (24577, 13),
]

LITLEN_SYMBOLS = 286  # 0-255 リテラル, 256 EOB, 257-285 長さ
DIST_SYMBOLS = 30
END_OF_BLOCK = 256

# 符号長アルファベット(RFC 1951 3.2.7): 0-15 は長さそのもの、
# 16 = 直前の長さを 3-6 回、17 = ゼロを 3-10 回、18 = ゼロを 11-138 回
CLEN_SYMBOLS = 19
# 符号長の出現しやすい順。末尾のゼロを落とすためだけに並べ替えてある
CLEN_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
# 実 DEFLATE はここを 3bit = 符号長 7 上限にしている。こちらは package-merge を
# 15bit で効かせているので 4bit。3bit まで詰めるには符号長符号側にも 7bit 制限が要る
CLEN_BITS = 4


def _bucket(table, value):
    """value を含むグループの (符号番号, 追加ビット値, 追加ビット数)。"""
    for i in range(len(table) - 1, -1, -1):
        base, extra = table[i]
        if value >= base:
            return i, value - base, extra
    raise ValueError(f"表の範囲外: {value}")


def _rle_lengths(lens):
    """符号長列を符号長アルファベットの (記号, 追加ビット値, 追加ビット数) へ畳む。

    litlen と dist を連結した 1 本として畳む。DEFLATE の符号長表は
    「使わない記号 = 長さ 0」が連続するので、ここで大半が消える。
    """
    plan = []
    i = 0
    n = len(lens)
    while i < n:
        v = lens[i]
        run = 1
        while i + run < n and lens[i + run] == v:
            run += 1
        i += run
        if v:
            plan.append((v, 0, 0))  # 16 は「直前と同じ」なので 1 個は素で置く
            run -= 1
            while run >= 3:
                take = min(run, 6)
                plan.append((16, take - 3, 2))
                run -= take
        else:
            while run >= 11:
                take = min(run, 138)
                plan.append((18, take - 11, 7))
                run -= take
            while run >= 3:
                take = min(run, 10)
                plan.append((17, take - 3, 3))
                run -= take
        plan.extend([(v, 0, 0)] * run)
    return plan


def _write_lengths(w, lens):
    plan = _rle_lengths(lens)
    clen_freq = [0] * CLEN_SYMBOLS
    for sym, _, _ in plan:
        clen_freq[sym] += 1
    clen_lens = huffman.code_lengths(clen_freq, limit=(1 << CLEN_BITS) - 1)
    clen_codes = huffman.canonical(clen_lens)

    count = CLEN_SYMBOLS
    while count > 4 and clen_lens[CLEN_ORDER[count - 1]] == 0:
        count -= 1
    w.write(count - 4, 4)
    for i in range(count):
        w.write(clen_lens[CLEN_ORDER[i]], CLEN_BITS)

    for sym, extra_val, extra_bits in plan:
        c, l = clen_codes[sym]
        w.write(c, l)
        if extra_bits:
            w.write(extra_val, extra_bits)


def _read_lengths(r, count):
    clen_lens = [0] * CLEN_SYMBOLS
    for i in range(r.read(4) + 4):
        clen_lens[CLEN_ORDER[i]] = r.read(CLEN_BITS)
    table = huffman.decoder_table(clen_lens)

    lens = []
    while len(lens) < count:
        sym = huffman.read_symbol(r, table)
        if sym < 16:
            lens.append(sym)
        elif sym == 16:
            lens += [lens[-1]] * (3 + r.read(2))
        elif sym == 17:
            lens += [0] * (3 + r.read(3))
        else:
            lens += [0] * (11 + r.read(7))
    return lens


def encode(data, chain_limit=64):
    toks = lz77.tokens(data, chain_limit)

    litlen_freq = [0] * LITLEN_SYMBOLS
    dist_freq = [0] * DIST_SYMBOLS
    plan = []
    for t in toks:
        if len(t) == 1:
            litlen_freq[t[0]] += 1
            plan.append((t[0], 0, 0, None))
        else:
            dist, length = t
            lc, lx, lb = _bucket(LENGTH_CODES, length)
            dc, dx, db = _bucket(DIST_CODES, dist)
            litlen_freq[257 + lc] += 1
            dist_freq[dc] += 1
            plan.append((257 + lc, lx, lb, (dc, dx, db)))
    litlen_freq[END_OF_BLOCK] += 1

    # 符号長は CLEN アルファベット(0-15)で送るため、木を 15bit に収める
    litlen_lens = huffman.code_lengths(litlen_freq, limit=15)
    dist_lens = huffman.code_lengths(dist_freq, limit=15)
    litlen_codes = huffman.canonical(litlen_lens)
    dist_codes = huffman.canonical(dist_lens)

    w = BitWriter()
    _write_lengths(w, litlen_lens + dist_lens)
    for sym, extra_val, extra_bits, dpart in plan:
        c, l = litlen_codes[sym]
        w.write(c, l)
        if extra_bits:
            w.write(extra_val, extra_bits)
        if dpart:
            dc, dx, db = dpart
            c, l = dist_codes[dc]
            w.write(c, l)
            if db:
                w.write(dx, db)
    c, l = litlen_codes[END_OF_BLOCK]
    w.write(c, l)
    return w.bytes()


def decode(blob):
    r = BitReader(blob)
    lens = _read_lengths(r, LITLEN_SYMBOLS + DIST_SYMBOLS)
    litlen_table = huffman.decoder_table(lens[:LITLEN_SYMBOLS])
    dist_table = huffman.decoder_table(lens[LITLEN_SYMBOLS:])

    out = bytearray()
    while True:
        sym = huffman.read_symbol(r, litlen_table)
        if sym == END_OF_BLOCK:
            return bytes(out)
        if sym < 256:
            out.append(sym)
            continue
        base, extra = LENGTH_CODES[sym - 257]
        length = base + (r.read(extra) if extra else 0)
        dsym = huffman.read_symbol(r, dist_table)
        dbase, dextra = DIST_CODES[dsym]
        dist = dbase + (r.read(dextra) if dextra else 0)
        start = len(out) - dist
        if dist >= length:
            out += out[start : start + length]
        else:
            # 参照元と書き先が重なる場合だけは 1 バイトずつ。
            # 「1 バイトの繰り返しで埋める」用法がここに来る
            for k in range(length):
                out.append(out[start + k])
