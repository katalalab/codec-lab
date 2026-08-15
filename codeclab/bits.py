"""ビット単位 I/O。全エントロピー符号の土台。

MSB-first で統一している。実物の DEFLATE は「ハフマン符号は MSB から、
その他の値は LSB から」という混在方式だが、ここでは読みやすさを取った。
zip と bit-exact な出力が要るようになったら deflate.py 側で詰める。

読み書きとも 1 ビットずつ触らず、アキュムレータへ積んでバイト単位で
出し入れする。実装の定石で、Python では関数呼び出し回数がそのまま速度に出る。
"""

# 一度に補充するバイト数。2→16 で復号が伸び、それ以上は横ばい(実測)
_REFILL = 16


class BitWriter:
    def __init__(self):
        self._out = bytearray()
        self._acc = 0
        self._n = 0

    def bit(self, b):
        self._acc = (self._acc << 1) | (b & 1)
        self._n += 1
        if self._n == 8:
            self._out.append(self._acc)
            self._acc = 0
            self._n = 0

    def write(self, value, nbits):
        acc = (self._acc << nbits) | (value & ((1 << nbits) - 1))
        total = self._n + nbits
        rest = total & 7
        if total >= 8:
            self._out += (acc >> rest).to_bytes(total >> 3, "big")
            acc &= (1 << rest) - 1
        self._acc = acc
        self._n = rest

    def bytes(self):
        if self._n == 0:
            return bytes(self._out)
        return bytes(self._out) + bytes([self._acc << (8 - self._n)])


class BitReader:
    def __init__(self, data):
        self._data = data
        self._next = 0  # 次に補充するバイト位置
        self._acc = 0  # 下位 _n ビットが未消費。先頭のビットが最上位
        self._n = 0

    def _fill(self, nbits):
        # 消費済みの上位ビットはここで捨てる。放っておくと acc が無限に伸びる
        acc = self._acc & ((1 << self._n) - 1)
        n = self._n
        pos = self._next
        while n < nbits:
            chunk = self._data[pos : pos + _REFILL]
            pos += _REFILL
            # 末尾を越えた分は 0 で埋める: 最終バイトのパディングと同じ扱い。
            # 算術符号がこの「越えたら 0」に依存している
            acc = (acc << (_REFILL * 8)) | (
                int.from_bytes(chunk, "big") << ((_REFILL - len(chunk)) * 8)
            )
            n += _REFILL * 8
        self._acc = acc
        self._n = n
        self._next = pos

    def bit(self):
        if self._n == 0:
            self._fill(1)
        n = self._n = self._n - 1
        return (self._acc >> n) & 1

    def read(self, nbits):
        if self._n < nbits:
            self._fill(nbits)
        n = self._n = self._n - nbits
        return (self._acc >> n) & ((1 << nbits) - 1)

    def peek(self, nbits):
        """消費せずに先読みする。表駆動ハフマン復号のための入口。"""
        if self._n < nbits:
            self._fill(nbits)
        return (self._acc >> (self._n - nbits)) & ((1 << nbits) - 1)

    def skip(self, nbits):
        """peek 済みのビットを捨てる。補充は peek が済ませている前提。"""
        self._n -= nbits
