"""正準ハフマン符号。DEFLATE(zip/png/gzip)・JPEG・JPEG XL が使う形。

「正準」の効きどころは、符号長だけ送れば復号側が符号表を再構成できる点。
木そのものを送らずに済むので、ヘッダが 256 バイトで足りる。
"""

import heapq

from .bits import BitReader, BitWriter


def _package_merge(freqs, limit):
    """長さ制限つきハフマン (Larmore-Hirschberg の package-merge)。

    実 DEFLATE が 15bit、JPEG が 16bit の上限を仕様に書いているのは飾りではない。
    符号長表自体が上限つきの形式で送られるので、木が深くなった瞬間にヘッダが
    表現できなくなる。フィボナッチ頻度の敵対的入力で実際に破綻した(adversarial.py A)。
    """
    items = sorted((f, s) for s, f in enumerate(freqs) if f)
    n = len(items)
    if (1 << limit) < n:
        raise ValueError(f"符号長上限 {limit} では {n} 記号を表現できない")
    nodes = [(f, (s,)) for f, s in items]
    cur = nodes
    for _ in range(limit - 1):
        packages = [
            (cur[k][0] + cur[k + 1][0], cur[k][1] + cur[k + 1][1])
            for k in range(0, len(cur) - 1, 2)
        ]
        cur = sorted(nodes + packages)
    lens = [0] * len(freqs)
    for _, syms in cur[: 2 * n - 2]:
        for s in syms:
            lens[s] += 1
    return lens


def code_lengths(freqs, limit=None):
    """記号ごとの符号長を返す。使わない記号は 0。

    limit を渡すとその長さ以内に収める。まず制限なしで組み、収まっていれば
    そのまま返す — 制限なしのハフマンは最適なので、収まる限りそちらが良い。
    """
    if limit is not None:
        lens = code_lengths(freqs)
        if max(lens, default=0) <= limit:
            return lens
        return _package_merge(freqs, limit)

    present = [s for s, f in enumerate(freqs) if f]
    if not present:
        return [0] * len(freqs)
    if len(present) == 1:
        # 1 記号でも 1bit は要る: 長さ 0 の符号は復号側で区切れない
        lens = [0] * len(freqs)
        lens[present[0]] = 1
        return lens

    heap = [(freqs[s], s, [s]) for s in present]
    heapq.heapify(heap)
    lens = [0] * len(freqs)
    while len(heap) > 1:
        f1, s1, g1 = heapq.heappop(heap)
        f2, s2, g2 = heapq.heappop(heap)
        for s in g1 + g2:
            lens[s] += 1
        heapq.heappush(heap, (f1 + f2, min(s1, s2), g1 + g2))
    return lens


def canonical(lens):
    """符号長から正準符号を作る。 {記号: (符号値, 長さ)}"""
    codes = {}
    code = 0
    for length in range(1, max(lens, default=0) + 1):
        for sym, l in enumerate(lens):
            if l == length:
                codes[sym] = (code, length)
                code += 1
        code <<= 1
    return codes


# ルートテーブル長。8〜12 を実測したが差は測定ノイズに埋もれたので中央を取った
ROOT_BITS = 10


def root_table(lens):
    """先頭 ROOT_BITS ビットで 1 回引くだけの表。要素は (記号, 実際の符号長)。

    zlib と同じ表駆動。符号が ROOT_BITS より短いときは後続の任意ビット列を
    同じ要素へ潰しておき、引いた後に実際の長さだけ進める。
    ROOT_BITS を超える符号と未使用のビット列は (-1, 0) にして呼び出し側で
    ビット単位の探索へ落とす。長い符号 = 稀な記号なので全体には効かない。
    """
    tbl = [(-1, 0)] * (1 << ROOT_BITS)
    for sym, (code, length) in canonical(lens).items():
        if length > ROOT_BITS:
            continue
        fill = 1 << (ROOT_BITS - length)
        base = code << (ROOT_BITS - length)
        tbl[base : base + fill] = [(sym, length)] * fill
    return tbl


def decoder_table(lens):
    """復号表。ルートテーブルと、そこから溢れる符号用の {(長さ, 符号値): 記号}"""
    return root_table(lens), {(l, c): s for s, (c, l) in canonical(lens).items()}


def read_symbol(reader, table):
    root, rest = table
    sym, length = root[reader.peek(ROOT_BITS)]
    if length:
        reader.skip(length)
        return sym
    code = 0
    length = 0
    while True:
        code = (code << 1) | reader.bit()
        length += 1
        if (length, code) in rest:
            return rest[(length, code)]
        if length > 64:
            raise ValueError("ハフマン符号が壊れている")


def encode(data):
    freqs = [0] * 256
    for b in data:
        freqs[b] += 1
    lens = code_lengths(freqs)
    codes = canonical(lens)
    w = BitWriter()
    for b in data:
        c, l = codes[b]
        w.write(c, l)
    return bytes(lens) + len(data).to_bytes(4, "big") + w.bytes()


def decode(blob):
    lens = list(blob[:256])
    n = int.from_bytes(blob[256:260], "big")
    table = decoder_table(lens)
    r = BitReader(blob[260:])
    return bytes(read_symbol(r, table) for _ in range(n))
