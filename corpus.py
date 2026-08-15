"""ベンチ用のテストデータ。外部ファイルなしで再現できるよう全部生成する。

圧縮率は素材で桁が変わるので、性質の違う 5 種を固定で用意した。
乱数は LCG 固定シードなので、いつ・どのマシンで走らせても同じ列になる。
"""

import math

WORDS = (
    "the of and to in a is that for it as was with be by on not he i this "
    "but had are or have from an they which one you were her all she there "
    "would their we him been has when who will more no if out so said what"
).split()


def _lcg(seed=88172645463325252):
    x = seed
    while True:
        x = (x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        yield x >> 33


def text(size=200_000):
    r = _lcg()
    out = []
    n = 0
    while n < size:
        w = WORDS[next(r) % len(WORDS)]
        out.append(w)
        n += len(w) + 1
        if next(r) % 12 == 0:
            out.append("\n")
    return " ".join(out)[:size].encode()


def source_like(size=200_000):
    """繰り返し構造の強いデータ。LZ 系が最も効く形。"""
    template = (
        "def handler_%d(request, context):\n"
        "    payload = request.get('payload', {})\n"
        "    if not payload:\n"
        "        return {'status': 400, 'body': 'empty'}\n"
        "    return {'status': 200, 'body': payload}\n\n"
    )
    out = "".join(template % i for i in range(size // len(template % 0) + 1))
    return out[:size].encode()


def image_rgb(width=128, height=128):
    """グラデーション + 低周波ノイズの RGB8。PNG フィルタ層の題材。"""
    r = _lcg(12345)
    noise = [next(r) % 24 for _ in range(width * height)]
    out = bytearray()
    for y in range(height):
        for x in range(width):
            n = noise[y * width + x]
            out.append((x * 2 + n) & 0xFF)
            out.append((y * 2 + n) & 0xFF)
            out.append((x + y + n) & 0xFF)
    return bytes(out), width, height, 3


def audio_pcm(n=48_000, rate=48_000):
    """倍音 + 微小ノイズの int16 モノラル。LPC / MDCT の題材。"""
    r = _lcg(999)
    out = []
    for i in range(n):
        t = i / rate
        v = (
            9000 * math.sin(2 * math.pi * 220 * t)
            + 3000 * math.sin(2 * math.pi * 440 * t + 0.4)
            + 900 * math.sin(2 * math.pi * 1320 * t)
        )
        out.append(max(-32768, min(32767, int(v) + (next(r) % 65 - 32))))
    return out


def incompressible(size=100_000):
    r = _lcg(4242)
    return bytes(next(r) & 0xFF for _ in range(size))


def byte_corpus():
    """bytes -> bytes コーデックに食わせる素材一式。"""
    img, w, h, bpp = image_rgb()
    return {
        "text": text(),
        "source": source_like(),
        "image_raw": img,
        "audio_le16": b"".join(
            (s & 0xFFFF).to_bytes(2, "little") for s in audio_pcm(24_000)
        ),
        "random": incompressible(),
    }
