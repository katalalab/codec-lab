#!/usr/bin/env python3
"""敵対的入力での検証。test_codecs.py が通ることは、壊れないことを意味しない。

攻撃者が選べるのは入力だけなので、入力だけで壊せるかを調べる。

  A 頻度分布を選んでハフマン符号長を仕様上限より伸ばす
  C 参照距離を出力長より大きくする(Python の負インデックスは黙って巻き戻る)
  D 展開後サイズを入力の数百万倍にする(decompression bomb)
  E 頻度正規化の丸めを崩す
  F 予測器に int16 の外を食わせる
  G LZW の符号幅拡張の境界を全長で総当たりする

破損ビットストリームでの停止性(B)は無限ループの可能性があるため、
このスクリプトではなく外から timeout 付きの別プロセスで確認する。
"""

from codeclab import deflate, huffman, lpc, lz77, lzw, rans
from codeclab.bits import BitWriter

FINDINGS = []


def report(tag, ok, detail):
    print(f"{'ok  ' if ok else 'FAIL'} {tag}: {detail}")
    if not ok:
        FINDINGS.append((tag, detail))


def _fib_freqs(n):
    """フィボナッチ頻度。ハフマン木を最も深くする既知の最悪ケース。"""
    freqs = [0] * 256
    a, b = 1, 1
    for i in range(n):
        freqs[i] = a
        a, b = b, a + b
    return freqs


def _shuffled(freqs, seed=7):
    syms = []
    for s, f in enumerate(freqs):
        syms += [s] * f
    x = seed
    for i in range(len(syms) - 1, 0, -1):
        x = (x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        j = (x >> 33) % (i + 1)
        syms[i], syms[j] = syms[j], syms[i]
    return bytes(syms)


def check_huffman_length_limit():
    for n in (16, 20, 24):
        lens = huffman.code_lengths(_fib_freqs(n))
        report(
            f"A huffman/符号長上限 記号{n}",
            max(lens) <= 15,
            f"最大符号長 {max(lens)} (DEFLATE 仕様上限 15 / JPEG 16)",
        )


def check_deflate_on_skewed():
    for n in (16, 20, 24):
        data = _shuffled(_fib_freqs(n))
        try:
            blob = deflate.encode(data)
            ok = deflate.decode(blob) == data
            detail = f"{len(data)}B -> {len(blob)}B / 往復{'一致' if ok else '不一致'}"
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        report(f"A deflate/歪んだ頻度分布 記号{n}", ok, detail)


def check_backref_underflow():
    for dist, expect in ((15, "巻き戻り"), (100, "IndexError")):
        w = BitWriter()
        for b in b"abcdefghij":
            w.bit(0)
            w.write(b, 8)
        w.bit(1)
        w.write(dist - 1, 15)
        w.write(20 - lz77.MIN_MATCH, 8)
        blob = (30).to_bytes(4, "big") + w.bytes()
        try:
            out = lz77.decode(blob)
            report(
                f"C lz77/出力長10 に対し距離{dist}",
                False,
                f"例外なく {len(out)}B 返した({expect}で黙って別データになる)",
            )
        except IndexError:
            report(f"C lz77/出力長10 に対し距離{dist}", True, "IndexError で停止")


def check_expansion_bomb():
    n = 1_000_000
    blob = n.to_bytes(4, "big") + b"\x00"
    out = lz77.decode(blob)
    report(
        "D lz77/展開爆弾",
        False,
        f"入力 {len(blob)}B から {len(out):,}B を生成 (倍率 {len(out) // len(blob):,}x / "
        f"長さヘッダは 4 バイトなので上限は 4GiB)",
    )


def check_rans_normalize():
    for name, freqs in (
        ("1記号に集中", [10**9] + [1] * 255),
        ("全記号が等頻度", [1] * 256),
        ("2記号のみ", [10**9, 1] + [0] * 254),
    ):
        try:
            out = rans.normalize(freqs)
            live = [f for f in out if f]
            ok = sum(out) == rans.SCALE and min(live) >= 1
            detail = f"合計 {sum(out)} / 最小 {min(live)} / 最大 {max(out)}"
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        report(f"E rans/頻度正規化 {name}", ok, detail)


def check_lpc_range():
    for bits, name in ((15, "int16"), (23, "int24"), (31, "int32")):
        s = [(-1) ** i * ((1 << bits) - 1 - i) for i in range(64)]
        try:
            ok = lpc.decode(lpc.encode(s)) == s
            detail = "往復一致" if ok else "往復不一致 (warmup が 32bit に収まらない)"
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        report(f"F lpc/{name} 相当のサンプル", ok, detail)


def check_lzw_boundaries():
    bad = []
    for n in range(400, 6000, 7):
        data = bytes((i * 31 + i // 251) & 0xFF for i in range(n))
        if lzw.decode(lzw.encode(data)) != data:
            bad.append(("非反復", n))
    for n in range(100, 3000, 11):
        data = (b"abcab" * n)[:n]
        if lzw.decode(lzw.encode(data)) != data:
            bad.append(("反復", n))
    report("G lzw/符号幅拡張の境界", not bad, f"{len(bad)} 件不一致 {bad[:5]}" if bad else "全長で一致")


if __name__ == "__main__":
    for fn in (
        check_huffman_length_limit,
        check_deflate_on_skewed,
        check_backref_underflow,
        check_expansion_bomb,
        check_rans_normalize,
        check_lpc_range,
        check_lzw_boundaries,
    ):
        fn()
    print(f"\n{len(FINDINGS)} findings")
