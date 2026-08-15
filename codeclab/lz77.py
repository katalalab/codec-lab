"""LZ77 / LZSS。zip・gzip・png・zstd・lz4 の「辞書層」の共通祖先。

過去の出力そのものを辞書として (距離, 長さ) で参照する。ハッシュチェーンで
候補位置を絞るのは zlib と同じ作戦で、chain_limit が圧縮率と速度のつまみ。
パースも zlib の deflate_slow と同じ lazy matching: 位置 i のマッチより
i+1 のマッチが長ければ i をリテラルに落とす。貪欲法との差が DEFLATE の
圧縮率の主因になっている。

zlib との差分:
- ハッシュ鍵は 3 バイトをそのまま整数化したもので衝突なし。実物は 15bit へ
  潰して衝突を先頭バイト比較で弾く。
- 距離の上限が 32767(実物は 32768)。チェーンのリングが上書きされる前に
  打ち切るため。空いた 32768 番を下のリテラル連続符号に転用している。
- lz77 単体のビット列は固定長 (リテラル 1+8 / マッチ 1+15+8 /
  リテラル連続 1+15+8+8k)。実物の DEFLATE はこの層をハフマンに掛ける
  ので、deflate.py は tokens() だけを共有してビット列は自前で持つ。
"""

from array import array

from .bits import BitReader, BitWriter

WINDOW = 1 << 15  # 32KiB。DEFLATE と同じ
MIN_MATCH = 3
MAX_MATCH = 258

# 距離の上限。候補の連結リスト prev[] は WINDOW 個のリングなので、
# pos の要素が pos+WINDOW の挿入で潰される前に walk を打ち切る必要がある。
MAX_DIST = WINDOW - 1

# zlib level 6 相当のつまみ。lazy は素直にやると探索が倍働くので、
# 十分なマッチが取れた時点で打ち切って元を取る。
GOOD_MATCH = 8  # 保留中のマッチがこれ以上ならチェーンを 1/4 に浅くする
MAX_LAZY = 16  # これ以上のマッチは lazy 判定を省いて即採用
NICE_MATCH = 128  # これ以上伸びたらチェーン探索を止める

# リテラル連続の符号。MAX_DIST で距離 32768 を使わないと決めた分、その
# 符号 (dist-1 = 0x7FFF) が空くので「以降 k バイトは生」の合図に転用する。
# 頭が 24bit 付くので 24 + 8k < 9k、つまり 25 個以上まとまって初めて得。
RUN_ESCAPE = WINDOW - 1
MIN_RUN = 25
MAX_RUN = 256


def tokens(data, chain_limit=64, lazy=True):
    """(literal,) か (距離, 長さ) の列にする。"""
    n = len(data)
    mask = WINDOW - 1
    heads = {}  # 3 バイト鍵 -> 直近の出現位置
    # 位置 -> 同じ鍵の 1 つ前の位置。WINDOW 周期のリングなので、窓から
    # 外れた位置は上書きで自然に消える(明示的な掃除が要らない)。
    prev = array("i", [-1]) * WINDOW
    out = []
    # lazy 判定のために 1 つ前の位置で見つけたマッチを持ち越す枠
    hold_pos = hold_dist = hold_len = 0
    i = 0
    while i < n:
        best_len, best_dist = 0, 0
        if i + MIN_MATCH <= n:
            key = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
            pos = heads.get(key, -1)
            heads[key] = i
            prev[i & mask] = pos
            limit = min(MAX_MATCH, n - i)
            chain = chain_limit >> 2 if hold_len >= GOOD_MATCH else chain_limit
            while pos >= 0 and chain:
                dist = i - pos
                if dist > MAX_DIST:
                    break
                chain -= 1
                # 現 best の末尾が違えばこの候補は届かない。全比較を省く
                if best_len and data[pos + best_len] != data[i + best_len]:
                    pos = prev[pos & mask]
                    continue
                l = MIN_MATCH
                while l < limit and data[pos + l] == data[i + l]:
                    l += 1
                if l > best_len:
                    best_len, best_dist = l, dist
                    if l >= NICE_MATCH or l == limit:
                        break
                pos = prev[pos & mask]

        if hold_len:
            if best_len > hold_len:
                # 1 つ先の方が長い: 保留分はリテラルに落として先を採る
                out.append((data[hold_pos],))
                hold_pos, hold_dist, hold_len = i, best_dist, best_len
                i += 1
                continue
            emit_pos, emit_dist, emit_len = hold_pos, hold_dist, hold_len
            hold_len = 0
        elif best_len and lazy and best_len < MAX_LAZY:
            # マッチはあるが確定させず、次の位置と比べる。マッチが立つのは
            # i <= n-3 の位置だけなので、保留したまま列が終わることはない
            hold_pos, hold_dist, hold_len = i, best_dist, best_len
            i += 1
            continue
        elif best_len:
            emit_pos, emit_dist, emit_len = i, best_dist, best_len
        else:
            out.append((data[i],))
            i += 1
            continue

        out.append((emit_dist, emit_len))
        end = emit_pos + emit_len
        for j in range(i + 1, end):  # 飛ばす範囲もハッシュには入れておく
            if j + MIN_MATCH <= n:
                k = (data[j] << 16) | (data[j + 1] << 8) | data[j + 2]
                prev[j & mask] = heads.get(k, -1)
                heads[k] = j
        i = end
    return out


def _copy(out, dist, length):
    start = len(out) - dist
    if dist >= length:
        out += out[start : start + length]  # 重ならないので一括で写せる
    else:
        # 自己重複コピーは直近 dist バイトの周期になる。繰り返して切る
        period = out[start:]
        out += (period * (length // dist + 1))[:length]


def apply_tokens(toks):
    out = bytearray()
    for t in toks:
        if len(t) == 1:
            out.append(t[0])
        else:
            _copy(out, *t)
    return bytes(out)


def encode(data, chain_limit=64, lazy=True):
    w = BitWriter()
    toks = tokens(data, chain_limit)
    k, ntok = 0, len(toks)
    while k < ntok:
        t = toks[k]
        if len(t) == 2:
            dist, length = t
            w.bit(1)
            w.write(dist - 1, 15)
            w.write(length - MIN_MATCH, 8)
            k += 1
            continue
        j = k  # リテラルが続く区間 [k, j)
        while j < ntok and len(toks[j]) == 1:
            j += 1
        while j - k >= MIN_RUN:
            m = min(MAX_RUN, j - k)
            w.bit(1)
            w.write(RUN_ESCAPE, 15)
            w.write(m - 1, 8)
            for lit in toks[k : k + m]:
                w.write(lit[0], 8)
            k += m
        for lit in toks[k:j]:
            w.bit(0)
            w.write(lit[0], 8)
        k = j
    return len(data).to_bytes(4, "big") + w.bytes()


def decode(blob):
    n = int.from_bytes(blob[:4], "big")
    r = BitReader(blob[4:])
    out = bytearray()
    while len(out) < n:
        if not r.bit():
            out.append(r.read(8))
            continue
        d = r.read(15)
        if d == RUN_ESCAPE:
            for _ in range(r.read(8) + 1):
                out.append(r.read(8))
            continue
        dist = d + 1
        _copy(out, dist, r.read(8) + MIN_MATCH)
    return bytes(out)
