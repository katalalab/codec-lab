"""静的 rANS (range Asymmetric Numeral Systems)。

算術符号と同じ圧縮率を、乗除算 1 回ずつ・分岐ほぼ無しで出す。
zstd(FSE=tANS)、AV1、JPEG XL、Oodle が採用しているのはこれ。

特徴的なのは「符号化は逆順、復号は正順」であること。状態 x が
スタックとして働くので、最後に入れた記号から取り出される。
"""

SCALE_BITS = 12
SCALE = 1 << SCALE_BITS
LOWER = 1 << 23  # 状態の下限。バイト単位で正規化する


def normalize(freqs):
    """頻度を合計ちょうど SCALE に丸める。出現する記号は必ず 1 以上。"""
    total = sum(freqs)
    out = [max(1, f * SCALE // total) if f else 0 for f in freqs]
    biggest = max(range(len(out)), key=lambda i: out[i])
    out[biggest] += SCALE - sum(out)
    if out[biggest] <= 0:
        raise ValueError("SCALE_BITS が記号数に対して小さすぎる")
    return out


def _cumulative(freq):
    cum = [0] * (len(freq) + 1)
    for i, f in enumerate(freq):
        cum[i + 1] = cum[i] + f
    return cum


def encode(data):
    if not data:
        return (0).to_bytes(4, "big") + bytes(512)

    raw = [0] * 256
    for b in data:
        raw[b] += 1
    freq = normalize(raw)
    cum = _cumulative(freq)

    out = bytearray()
    x = LOWER
    for sym in reversed(data):
        f = freq[sym]
        x_max = ((LOWER >> SCALE_BITS) << 8) * f
        while x >= x_max:
            out.append(x & 0xFF)
            x >>= 8
        x = ((x // f) << SCALE_BITS) + (x % f) + cum[sym]
    for _ in range(4):
        out.append(x & 0xFF)
        x >>= 8

    header = len(data).to_bytes(4, "big") + b"".join(
        f.to_bytes(2, "big") for f in freq
    )
    return header + bytes(reversed(out))


def decode(blob):
    n = int.from_bytes(blob[:4], "big")
    if n == 0:
        return b""
    freq = [int.from_bytes(blob[4 + 2 * i : 6 + 2 * i], "big") for i in range(256)]
    cum = _cumulative(freq)

    slot = bytearray(SCALE)
    for sym, f in enumerate(freq):
        for s in range(cum[sym], cum[sym + 1]):
            slot[s] = sym

    body = blob[516:]
    x = int.from_bytes(body[:4], "big")
    pos = 4
    out = bytearray()
    for _ in range(n):
        s = x & (SCALE - 1)
        sym = slot[s]
        out.append(sym)
        x = freq[sym] * (x >> SCALE_BITS) + s - cum[sym]
        while x < LOWER:
            x = (x << 8) | body[pos]
            pos += 1
    return bytes(out)
