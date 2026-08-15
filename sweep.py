#!/usr/bin/env python3
"""可逆パイプラインの総当たり探索。素材 × 予測 × 辞書 × 符号化。

狙いは「可逆で、圧縮率が高く、転送も速い」組み合わせの発見。
圧縮率だけを見ると必ず遅い方に倒れるので、回線速度を入れた
有効スループットで評価する:

    有効スループット = 原サイズ / (圧縮後サイズ / 回線速度 + 復号時間)

回線が細ければ圧縮率が、太ければ復号速度が支配する。どこで逆転するかは
素材ごとに違い、それが探索の主目的。

結果は sweep.jsonl へ追記。設定キーで再開できるので、途中で止めてよい。
設定順は固定シードでシャッフルしてあるため、途中終了でも空間を偏りなく覆う。
"""

import argparse
import json
import math
import os
import platform
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from codeclab import arith, huffman, lz77, png_filter, rans, rice
from codeclab.bits import BitReader, BitWriter
from codeclab.pipeline import _ycocg_planes

ROOT = Path(__file__).resolve().parent
MASK64 = (1 << 64) - 1


# ---------------------------------------------------------------- 素材

def _lcg(seed):
    x = seed
    while True:
        x = (x * 6364136223846793005 + 1442695040888963407) & MASK64
        yield x >> 33


def _mat_text(n):
    words = ("the of and to in a is that for it as was with be by on not he this but had "
             "are or have from an they which one you were her all she there would their").split()
    r, out, total = _lcg(1), [], 0
    while total < n:
        w = words[next(r) % len(words)]
        out.append(w)
        total += len(w) + 1
    return " ".join(out)[:n].encode()


def _mat_source(n):
    t = ("def handler_%d(req, ctx):\n    payload = req.get('payload', {})\n"
         "    if not payload:\n        return {'status': 400}\n"
         "    return {'status': 200, 'body': payload}\n\n")
    return "".join(t % i for i in range(n // len(t % 0) + 2))[:n].encode()


def _mat_json(n):
    r, out = _lcg(2), []
    for i in range(n // 90 + 2):
        out.append('{"id":%d,"name":"user_%d","score":%d,"active":%s,"tags":["a","b"]}'
                   % (i, next(r) % 100000, next(r) % 1000, "true" if next(r) % 2 else "false"))
    return ("[" + ",\n".join(out) + "]")[:n].encode()


def _mat_csv(n):
    r, out = _lcg(3), ["id,ts,value,delta,flag"]
    for i in range(n // 40 + 2):
        out.append("%d,%d,%.4f,%d,%d" % (i, 1700000000 + i * 60, (next(r) % 100000) / 100, next(r) % 200 - 100, next(r) % 2))
    return "\n".join(out)[:n].encode()


def _mat_log(n):
    r, out = _lcg(4), []
    lv = ["INFO", "WARN", "ERROR", "DEBUG"]
    for i in range(n // 80 + 2):
        out.append("2026-08-16T%02d:%02d:%02d.%03dZ %s worker-%d handled request in %dms"
                   % (next(r) % 24, next(r) % 60, next(r) % 60, next(r) % 1000,
                      lv[next(r) % 4], next(r) % 16, next(r) % 5000))
    return "\n".join(out)[:n].encode()


def _mat_html(n):
    t = ('<div class="card"><h3>Item %d</h3><p>Description text for the item.</p>'
         '<a href="/item/%d">detail</a></div>\n')
    return "".join(t % (i, i) for i in range(n // 100 + 2))[:n].encode()


def _mat_image_gradient(n):
    r, out = _lcg(5), bytearray()
    w = 384  # 128px * RGB
    for i in range(n):
        x, y = (i % w) // 3, i // w
        out.append((x * 2 + y + (next(r) % 24)) & 0xFF)
    return bytes(out)


def _mat_image_photo(n):
    r, out = _lcg(6), bytearray()
    for i in range(n):
        x, y = (i % 384) / 128.0, i / 384.0
        v = 128 + 100 * math.sin(x * 0.7) * math.cos(y * 0.013) + (next(r) % 40 - 20)
        out.append(max(0, min(255, int(v))))
    return bytes(out)


def _mat_image_screenshot(n):
    """平坦な面と鋭いエッジ。UI スクリーンショットの統計に寄せてある。"""
    r, out = _lcg(7), bytearray()
    block, cur = 0, 240
    for i in range(n):
        if block == 0:
            block = 30 + next(r) % 900
            cur = (30, 240, 255, 60, 200)[next(r) % 5]
        block -= 1
        out.append(cur)
    return bytes(out)


def _mat_audio_tone(n):
    r, out = _lcg(8), bytearray()
    for i in range(n // 2):
        t = i / 48000
        v = int(9000 * math.sin(2 * math.pi * 220 * t) + 3000 * math.sin(2 * math.pi * 441 * t)
                + 900 * math.sin(2 * math.pi * 1320 * t)) + (next(r) % 65 - 32)
        out += (max(-32768, min(32767, v)) & 0xFFFF).to_bytes(2, "little")
    return bytes(out[:n])


def _mat_audio_noisy(n):
    r, out = _lcg(9), bytearray()
    prev = 0
    for i in range(n // 2):
        prev = max(-32768, min(32767, prev + (next(r) % 2001 - 1000)))
        out += (prev & 0xFFFF).to_bytes(2, "little")
    return bytes(out[:n])


def _mat_float64(n):
    import struct
    r, out = _lcg(10), bytearray()
    for i in range(n // 8):
        out += struct.pack("<d", math.sin(i * 0.001) * 1000 + (next(r) % 100) / 1000)
    return bytes(out[:n])


def _mat_dna(n):
    r = _lcg(11)
    return bytes(b"ACGT"[next(r) % 4] for _ in range(n))


def _mat_sorted_ints(n):
    r, out, v = _lcg(12), bytearray(), 0
    for _ in range(n // 4):
        v += next(r) % 1000
        out += (v & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out[:n])


def _mat_timestamps(n):
    r, out, v = _lcg(13), bytearray(), 1700000000000
    for _ in range(n // 8):
        v += next(r) % 5000
        out += v.to_bytes(8, "little")
    return bytes(out[:n])


def _mat_sparse(n):
    r, out = _lcg(14), bytearray(n)
    for _ in range(n // 50):
        out[next(r) % n] = next(r) & 0xFF
    return bytes(out)


def _mat_utf8_ja(n):
    r = _lcg(15)
    pool = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん日本語圧縮実験"
    return "".join(pool[next(r) % len(pool)] for _ in range(n // 3 + 2)).encode()[:n]


def _mat_random(n):
    r = _lcg(16)
    return bytes(next(r) & 0xFF for _ in range(n))


MATERIALS = {
    "text": _mat_text, "source": _mat_source, "json": _mat_json, "csv": _mat_csv,
    "log": _mat_log, "html": _mat_html, "img_gradient": _mat_image_gradient,
    "img_photo": _mat_image_photo, "img_screenshot": _mat_image_screenshot,
    "audio_tone": _mat_audio_tone, "audio_noisy": _mat_audio_noisy,
    "float64": _mat_float64, "dna": _mat_dna, "sorted_ints": _mat_sorted_ints,
    "timestamps": _mat_timestamps, "sparse": _mat_sparse, "utf8_ja": _mat_utf8_ja,
    "random": _mat_random,
}

SIZES = (16_384, 65_536, 262_144, 1_048_576)


# ---------------------------------------------------------------- 予測層 (bytes -> bytes)

def _delta_enc(data, k):
    out = bytearray(data)
    for i in range(len(data) - 1, k - 1, -1):
        out[i] = (data[i] - data[i - k]) & 0xFF
    return bytes(out)


def _delta_dec(data, k):
    out = bytearray(data)
    for i in range(k, len(data)):
        out[i] = (out[i] + out[i - k]) & 0xFF
    return bytes(out)


def _png_enc(data, stride, bpp):
    """任意のバイト列を stride バイト/行の 2 次元とみなして PNG フィルタをかける。

    stride は「レコード長」の一般化。CSV の 1 行、RGB の 1 走査線、PCM の 1 フレームが
    どれもこれに当たる。stride が構造と噛み合うと予測が急に効く — 探索の主軸。
    """
    rows = len(data) // stride
    head = png_filter.filter_image(data[: rows * stride], stride // bpp, rows, bpp)
    return head + data[rows * stride :]


def _png_dec(data, stride, bpp, original_len):
    rows = original_len // stride
    body = rows * stride + rows  # フィルタ種別バイトが行ごとに 1 つ増える
    head = png_filter.unfilter_image(data[:body], stride // bpp, rows, bpp)
    return head + data[body:]


def _ycocg_enc(data):
    # RGB 3 バイト単位なので、3 で割り切れない末尾は変換せずそのまま後ろへ付ける
    n3 = len(data) // 3
    return b"".join(bytes(p) for p in _ycocg_planes(data[: n3 * 3])) + data[n3 * 3 :]


def _ycocg_dec(data, original_len):
    from codeclab import color
    n = original_len // 3
    y, co, cg, sign = (data[i * n : (i + 1) * n] for i in range(4))
    out = bytearray()
    for p in range(n):
        s = sign[p]
        out += bytes(color.ycocg_r_inv(y[p], co[p] - 256 * (s & 1), cg[p] - 256 * (s >> 1)))
    return bytes(out) + data[4 * n :]


def make_pre(spec):
    kind = spec[0]
    if kind == "none":
        return (lambda d: d), (lambda d, n: d)
    if kind == "delta":
        k = spec[1]
        return (lambda d: _delta_enc(d, k)), (lambda d, n: _delta_dec(d, k))
    if kind == "png":
        stride, bpp = spec[1], spec[2]
        return (lambda d: _png_enc(d, stride, bpp)), (lambda d, n: _png_dec(d, stride, bpp, n))
    if kind == "ycocg":
        return _ycocg_enc, _ycocg_dec
    raise ValueError(spec)


# ---------------------------------------------------------------- 符号化層

def _rice_enc(data):
    k = rice.best_k([b - 128 for b in data])
    w = BitWriter()
    w.write(k, 5)
    rice.write(w, [b - 128 for b in data], k)
    return len(data).to_bytes(4, "big") + w.bytes()


def _rice_dec(blob):
    n = int.from_bytes(blob[:4], "big")
    r = BitReader(blob[4:])
    k = r.read(5)
    return bytes((v + 128) & 0xFF for v in rice.read(r, n, k))


ENTROPY = {
    "huffman": (huffman.encode, huffman.decode),
    "rice": (_rice_enc, _rice_dec),
    "arith": (arith.encode, arith.decode),
    "rans": (rans.encode, rans.decode),
}


# ---------------------------------------------------------------- 設定空間

def _pre_specs():
    yield ("none",)
    for k in (1, 2, 3, 4, 6, 8, 12, 16):
        yield ("delta", k)
    for stride in (2, 3, 4, 6, 8, 12, 16, 32, 64, 128, 256, 384, 512, 1024):
        for bpp in (1, 2, 3, 4):
            if stride % bpp == 0:
                yield ("png", stride, bpp)
    yield ("ycocg",)


def _dict_specs():
    yield ("none",)
    for chain in (8, 32, 64, 256):
        for lazy in (False, True):
            yield ("lz77", chain, lazy)


def configs():
    out = []
    for mat in MATERIALS:
        for size in SIZES:
            for pre in _pre_specs():
                for dic in _dict_specs():
                    for ent in ENTROPY:
                        out.append((mat, size, pre, dic, ent))
    # 固定シードでシャッフル: 途中で止めても空間を偏りなく覆う
    r = _lcg(20260816)
    for i in range(len(out) - 1, 0, -1):
        j = next(r) % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def key_of(cfg):
    mat, size, pre, dic, ent = cfg
    return f"{mat}|{size}|{'-'.join(map(str, pre))}|{'-'.join(map(str, dic))}|{ent}"


# ---------------------------------------------------------------- 実行

_CACHE = {}


def material(mat, size):
    if (mat, size) not in _CACHE:
        _CACHE[(mat, size)] = MATERIALS[mat](size)
    return _CACHE[(mat, size)]


def run_one(cfg):
    mat, size, pre_spec, dict_spec, ent = cfg
    data = material(mat, size)
    pre_enc, pre_dec = make_pre(pre_spec)
    ent_enc, ent_dec = ENTROPY[ent]

    try:
        t0 = time.perf_counter()
        stage = pre_enc(data)
        if dict_spec[0] == "lz77":
            stage = lz77.encode(stage, chain_limit=dict_spec[1], lazy=dict_spec[2])
        blob = ent_enc(stage)
        enc_sec = time.perf_counter() - t0

        t0 = time.perf_counter()
        back = ent_dec(blob)
        if dict_spec[0] == "lz77":
            back = lz77.decode(back)
        back = pre_dec(back, len(data))
        dec_sec = time.perf_counter() - t0
    except Exception as e:
        return {"key": key_of(cfg), "material": mat, "size": size, "error": f"{type(e).__name__}: {e}"}

    return {
        "key": key_of(cfg), "material": mat, "size": size,
        "pre": "-".join(map(str, pre_spec)), "dict": "-".join(map(str, dict_spec)),
        "entropy": ent, "raw": len(data), "packed": len(blob),
        "ratio": len(blob) / len(data), "enc_sec": enc_sec, "dec_sec": dec_sec,
        "roundtrip": back == data,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "sweep.jsonl"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 4))
    ap.add_argument("--deadline", default="", help="HH:MM でこの時刻までに打ち切る")
    ap.add_argument("--limit", type=int, default=0, help="件数上限(動作確認用)")
    ap.add_argument("--shard", default="", help="i/N でこのノードの担当分だけ走らせる")
    args = ap.parse_args()

    cfgs = configs()
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        cfgs = [c for j, c in enumerate(cfgs) if j % n == i]

    done = set()
    out_path = Path(args.out)
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["key"])
                except Exception:
                    pass
    cfgs = [c for c in cfgs if key_of(c) not in done]
    if args.limit:
        cfgs = cfgs[: args.limit]

    deadline = None
    if args.deadline:
        h, m = (int(x) for x in args.deadline.split(":"))
        now = time.localtime()
        secs = (h - now.tm_hour) * 3600 + (m - now.tm_min) * 60 - now.tm_sec
        deadline = time.time() + (secs if secs > 0 else secs + 86400)

    host = platform.node()
    print(f"{len(cfgs)} configs / {args.workers} workers / 済み {len(done)}", flush=True)
    started = time.time()
    written = failed = broken = 0

    with out_path.open("a", encoding="utf-8") as f, ProcessPoolExecutor(args.workers) as pool:
        futures = {pool.submit(run_one, c): c for c in cfgs}
        for fut in as_completed(futures):
            row = fut.result()
            row["host"] = host
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
            if row.get("error"):
                failed += 1
            elif not row.get("roundtrip"):
                broken += 1
            if written % 500 == 0:
                rate = written / (time.time() - started)
                left = (len(cfgs) - written) / rate / 60
                f.flush()
                print(f"  {written}/{len(cfgs)}  {rate:.1f}/s  残り{left:.0f}分  "
                      f"エラー{failed} 往復不一致{broken}", flush=True)
            if deadline and time.time() > deadline:
                print("deadline 到達、打ち切り", flush=True)
                for g in futures:
                    g.cancel()
                break

    print(f"完了 {written} 件 / エラー {failed} / 往復不一致 {broken} / "
          f"{(time.time() - started) / 60:.1f}分", flush=True)


if __name__ == "__main__":
    main()
