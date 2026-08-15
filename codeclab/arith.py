"""算術符号(Witten-Neal-Cleary 型)。order-1 適応モデル + Fenwick tree。

ハフマンとの本質的な差は「1 記号 = 整数ビット」の制約を外せること。
確率 0.9 の記号を 0.15bit で書けるので、偏った分布で効く。
JPEG2000 の MQ-coder、H.264/HEVC の CABAC、ゼロ次算術符号は全部この系統。
直前 1 バイトで確率表を切り替えるのは CABAC のコンテキストモデリングの最小形。

省略: エスケープ(PPM)も文脈混合も入れていない。初出の文脈でも order-1 の表だけを
引くので、一様分布から学習し直すコストをそのまま払う。この学習コストがランダム
データでの膨張の正体で、初期頻度 init はそこと圧縮率の綱引きで決めてある。
"""

BITS = 32
TOP = 1 << BITS
QTR = TOP >> 2
HALF = QTR * 2
TQTR = QTR * 3
EOF = 256
NSYM = 257
START = 256  # 開始時の文脈。EOF は文脈として二度と現れないので枠を流用できる

# Fenwick 上の二分降下で使う跳び幅。NSYM 以下の最大 2 冪から 1 まで降ろす
_LIFTS = [1 << k for k in range(8, -1, -1)]


def _new_context(init):
    # 全記号が同じ頻度なので tree[i] は担当区間長 (i & -i) 個ぶんの合計になる
    tree = [0] + [init * (i & -i) for i in range(1, NSYM + 1)]
    return [[init] * NSYM, tree, init * NSYM]


def _rebuild(freq):
    tree = [0] * (NSYM + 1)
    for i in range(1, NSYM + 1):
        tree[i] += freq[i - 1]
        j = i + (i & -i)
        if j <= NSYM:
            tree[j] += tree[i]
    return tree


class Order1:
    """直前 1 バイトを文脈にした適応モデル。文脈ごとに Fenwick tree を 1 本持つ。

    累積頻度の取得も累積和からの逆引きも O(log 257)。線形走査だと復号側が
    記号あたり最大 257 回まわり、そこが全体の律速だった。
    257 文脈を先に作ると使わない表まで 6 万要素ぶん初期化するので遅延生成にする。

    init/increment が事前分布の強さで、大きいほど一様分布に張り付く。order-1 は
    文脈が 257 本に散って 1 本あたりの標本が減るので、order-0 のときの比 (1/32)
    のままだと乱数が 1.20 倍に膨らむ。限界は乱数で測って 2 に置いた。
    """

    def __init__(self, init=64, increment=32, limit=1 << 15):
        self.init = init
        self.increment = increment
        self.limit = limit
        self.slots = [None] * NSYM

    def range_of(self, ctx, sym):
        s = self.slots[ctx]
        if s is None:
            s = self.slots[ctx] = _new_context(self.init)
        tree = s[1]
        lo = 0
        i = sym
        while i:
            lo += tree[i]
            i -= i & -i
        return lo, lo + s[0][sym], s[2]

    def lookup(self, ctx, num, span):
        """符号語の位置から記号を逆引きする。

        目標値の計算に total が要り、その total は文脈ごとに違う。呼び出しを
        2 回に割らないため、目標値の算出もここでまとめて済ませる。
        """
        s = self.slots[ctx]
        if s is None:
            s = self.slots[ctx] = _new_context(self.init)
        tree = s[1]
        total = s[2]
        rem = (num * total - 1) // span
        lo = rem
        pos = 0
        for step in _LIFTS:
            nxt = pos + step
            if nxt <= NSYM and tree[nxt] <= rem:
                pos = nxt
                rem -= tree[nxt]
        lo -= rem  # 降下で消費したぶんがそのまま pos の累積下限
        return pos, lo, lo + s[0][pos], total

    def update(self, ctx, sym):
        s = self.slots[ctx]  # range_of / lookup が先に呼ばれるので必ず埋まっている
        freq = s[0]
        tree = s[1]
        inc = self.increment
        freq[sym] += inc
        i = sym + 1
        while i <= NSYM:
            tree[i] += inc
            i += i & -i
        total = s[2] + inc
        if total > self.limit:
            # 半減させて「最近の分布」に追従させる。忘却なしだと後半で固まる
            total = 0
            for k in range(NSYM):
                f = (freq[k] + 1) >> 1
                freq[k] = f
                total += f
            s[1] = _rebuild(freq)
        s[2] = total


def encode(data, model=None):
    m = model or Order1()
    range_of, update = m.range_of, m.update
    low, high, pending = 0, TOP - 1, 0
    out = bytearray()
    acc, nacc = 0, 0
    ctx = START

    for sym in list(data) + [EOF]:
        lo, hi, total = range_of(ctx, sym)
        span = high - low + 1
        high = low + span * hi // total - 1
        low = low + span * lo // total
        while True:
            if high < HALF:
                bit = 0
            elif low >= HALF:
                bit = 1
                low -= HALF
                high -= HALF
            elif low >= QTR and high < TQTR:
                # 収束しないまま中央をまたいでいる状態。判定を保留して桁だけ送る
                pending += 1
                low = (low - QTR) << 1
                high = ((high - QTR) << 1) | 1
                continue
            else:
                break
            # BitWriter 経由だと 1 ビットあたり関数呼び出しが 2 回入り、実測で
            # 符号化時間の半分がそこだった。ここだけ bits.py を使わず自前で詰める
            acc = (acc << 1) | bit
            nacc += 1
            if nacc == 8:
                out.append(acc)
                acc, nacc = 0, 0
            if pending:
                # 保留ぶんは反転ビットの連続。1 本ずつではなくまとめて流す
                acc = (acc << pending) | (0 if bit else (1 << pending) - 1)
                nacc += pending
                while nacc >= 8:
                    nacc -= 8
                    out.append((acc >> nacc) & 0xFF)
                acc &= (1 << nacc) - 1
                pending = 0
            low <<= 1
            high = (high << 1) | 1
        update(ctx, sym)
        ctx = sym

    # 最後に low の居場所を確定させる 1 ビットと、その反転(保留ぶん + 1 本)
    last = 0 if low < QTR else 1
    for bit in [last] + [1 - last] * (pending + 1):
        acc = (acc << 1) | bit
        nacc += 1
        if nacc == 8:
            out.append(acc)
            acc, nacc = 0, 0
    if nacc:
        # 端数は 0 で右詰め。復号側は末尾を越えたぶんを 0 として読む
        out.append(acc << (8 - nacc))
    return bytes(out)


def decode(blob, model=None):
    m = model or Order1()
    lookup, update = m.lookup, m.update
    head = BITS // 8
    value = int.from_bytes(blob[:head].ljust(head, b"\x00"), "big")
    pos, end = BITS, len(blob) * 8
    low, high = 0, TOP - 1
    out = bytearray()
    ctx = START
    while True:
        span = high - low + 1
        sym, lo, hi, total = lookup(ctx, value - low + 1, span)
        if sym == EOF:
            return bytes(out)
        out.append(sym)
        high = low + span * hi // total - 1
        low = low + span * lo // total
        while True:
            if high < HALF:
                pass
            elif low >= HALF:
                low -= HALF
                high -= HALF
                value -= HALF
            elif low >= QTR and high < TQTR:
                low -= QTR
                high -= QTR
                value -= QTR
            else:
                break
            low <<= 1
            high = (high << 1) | 1
            # 読み出しも自前。効きは素材次第で、記号あたりの出力ビットが多い
            # 高エントロピー素材ほど大きい(text +2%, image/audio/random +18〜24%)
            value = (value << 1) | (
                0 if pos >= end else (blob[pos >> 3] >> (7 - (pos & 7))) & 1
            )
            pos += 1
        update(ctx, sym)
        ctx = sym
