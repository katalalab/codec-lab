#!/usr/bin/env python3
"""assert だけの自己検査。`python test_codecs.py` で全部走る。

可逆を名乗る層は往復一致、標準に合わせた層は既知の実装と突き合わせる。
"""

import hashlib
import math
import zlib

import corpus
from codeclab import (
    LOSSLESS,
    color,
    crc32,
    dct,
    dwt,
    lpc,
    mdct,
    pipeline,
    png_filter,
    quant,
    sha256,
)


def test_lossless_roundtrip():
    cases = [
        b"",
        b"a",
        b"aaaaaaaaaaaaaaaaaaaaaaaa",
        bytes(range(256)),
        corpus.text(30_000),
        corpus.source_like(60_000),  # LZW の符号幅拡張をまたぐ長さ
        corpus.incompressible(5_000),
    ]
    for name, (enc, dec) in LOSSLESS.items():
        for i, data in enumerate(cases):
            assert dec(enc(data)) == data, f"{name} case{i} 往復不一致"


def test_hash_matches_reference():
    for data in (b"", b"abc", b"a" * 1000, corpus.text(5_000)):
        assert sha256.hexdigest(data) == hashlib.sha256(data).hexdigest()
        assert crc32.crc32(data) == zlib.crc32(data)


def test_png_filter_roundtrip():
    raw, w, h, bpp = corpus.image_rgb(64, 48)
    filtered = png_filter.filter_image(raw, w, h, bpp)
    assert png_filter.unfilter_image(filtered, w, h, bpp) == raw
    # 予測層が本当に効いているか: フィルタ後の方が deflate で縮む
    assert len(zlib.compress(filtered, 9)) < len(zlib.compress(raw, 9))


def test_lpc_roundtrip():
    pcm = corpus.audio_pcm(4096)
    assert lpc.decode(lpc.encode(pcm)) == pcm
    packed = len(lpc.encode(pcm))
    assert packed < len(pcm) * 2, "LPC + Rice が生 PCM より大きい"


def test_pipeline_image_roundtrip():
    raw, w, h, bpp = corpus.image_rgb(64, 48)
    baseline = len(zlib.compress(raw, 9))
    sizes = {}
    for name, (enc, dec) in pipeline.image_codecs(w, h, bpp).items():
        blob = enc(raw)
        assert dec(blob) == raw, f"{name} 往復不一致"
        sizes[name] = len(blob)
    # 合成の目的そのもの: 予測層を挟んだ方が生がけの zlib より縮み、
    # 色変換を足すとさらに縮む。ここが崩れたら層の順序か実装が壊れている。
    assert sizes["png_like"] < baseline
    assert sizes["ycocg_png"] < sizes["png_like"]


def test_pipeline_audio_roundtrip():
    pcm = b"".join((s & 0xFFFF).to_bytes(2, "little") for s in corpus.audio_pcm(4096))
    for name, (enc, dec) in pipeline.audio_codecs().items():
        blob = enc(pcm)
        assert dec(blob) == pcm, f"{name} 往復不一致"
        assert len(blob) < len(zlib.compress(pcm, 9)), f"{name} が zlib 生がけに負けている"


def test_dct_is_orthonormal():
    block = [[(x * 7 + y * 13) % 256 - 128 for x in range(8)] for y in range(8)]
    back = dct.idct_2d(dct.dct_2d(block))
    err = max(abs(back[y][x] - block[y][x]) for y in range(8) for x in range(8))
    assert err < 1e-9, f"DCT 往復誤差 {err}"


def test_dwt_reversible():
    sig = [(i * 37) % 251 - 125 for i in range(64)]
    lo, hi = dwt.haar(sig)
    assert dwt.ihaar(lo, hi) == sig
    s, d = dwt.cdf53(sig)
    assert dwt.icdf53(s, d) == sig


def test_mdct_perfect_reconstruction():
    n = 64
    sig = [math.sin(i * 0.07) + 0.3 * math.sin(i * 0.31) for i in range(512)]
    back = mdct.synthesize(mdct.analyze(sig, n), n, len(sig))
    err = max(abs(a - b) for a, b in zip(sig, back))
    assert err < 1e-9, f"MDCT の TDAC が成立していない: 誤差 {err}"


def test_color():
    for rgb in [(0, 0, 0), (255, 255, 255), (30, 200, 90), (128, 64, 200)]:
        y, cb, cr = color.rgb_to_ycbcr(*rgb)
        back = color.ycbcr_to_rgb(y, cb, cr)
        assert max(abs(a - b) for a, b in zip(rgb, back)) < 1e-9
        assert color.ycocg_r_inv(*color.ycocg_r(*rgb)) == rgb  # こちらは完全可逆


def test_quant_tables():
    assert sorted(quant.ZIGZAG) == sorted((y, x) for y in range(8) for x in range(8))
    assert quant.scale(quant.LUMA, 50) == quant.LUMA
    assert quant.scale(quant.LUMA, 95)[0][0] < quant.LUMA[0][0]
    assert quant.scale(quant.LUMA, 10)[0][0] > quant.LUMA[0][0]
    block = [[(x + y) * 8 - 64 for x in range(8)] for y in range(8)]
    seq = quant.to_zigzag(block)
    assert quant.from_zigzag(seq) == block


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
