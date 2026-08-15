#!/usr/bin/env python3
"""可逆コーデックを素材横断で回し、圧縮率と速度を results.jsonl に貯める。

往復不一致は即 FAIL。可逆を名乗るコーデックの検証はこれが全て。
zlib / lzma / bz2 を同じ表に並べてあるので、自作がどこに立っているかが
毎回そのまま出る。
"""

import argparse
import json
import platform
import time
from pathlib import Path

import corpus
from codeclab import BY_MATERIAL, LOSSLESS

ROOT = Path(__file__).resolve().parent


def measure(fn, arg):
    t = time.perf_counter()
    out = fn(arg)
    return out, time.perf_counter() - t


def codecs_for(material):
    """汎用コーデック + その素材専用の合成コーデック。"""
    builder = BY_MATERIAL.get(material)
    if not builder:
        return dict(LOSSLESS)
    # 画像だけは形を渡さないと復号できない。素材を作った corpus 側から取る。
    geom = corpus.image_rgb()[1:] if material == "image_raw" else ()
    return {**LOSSLESS, **builder(*geom)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codec", action="append", help="対象を絞る(複数可)")
    ap.add_argument("--material", action="append", help="素材を絞る(複数可)")
    ap.add_argument("--out", default=str(ROOT / "results.jsonl"))
    ap.add_argument("--note", default="", help="実験の意図を1行で残す")
    args = ap.parse_args()

    materials = corpus.byte_corpus()
    if args.material:
        materials = {k: v for k, v in materials.items() if k in args.material}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    rows, failed = [], []
    for mname, data in materials.items():
        codecs = {
            k: v
            for k, v in codecs_for(mname).items()
            if not args.codec or k in args.codec
        }
        for cname, (enc, dec) in codecs.items():
            try:
                blob, t_enc = measure(enc, data)
                back, t_dec = measure(dec, blob)
            except Exception as e:
                failed.append(f"{mname}/{cname}: {type(e).__name__}: {e}")
                continue
            if back != data:
                failed.append(f"{mname}/{cname}: 往復不一致")
                continue
            rows.append(
                {
                    "ts": stamp,
                    "host": platform.node(),
                    "material": mname,
                    "codec": cname,
                    "raw": len(data),
                    "packed": len(blob),
                    "ratio": len(blob) / len(data),
                    "enc_mbps": len(data) / t_enc / 1e6,
                    "dec_mbps": len(data) / t_dec / 1e6,
                    "note": args.note,
                }
            )

    with open(args.out, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{'material':11} {'codec':10} {'ratio':>7} {'saved':>7} {'enc':>9} {'dec':>9}")
    for r in sorted(rows, key=lambda r: (r["material"], r["ratio"])):
        print(
            f"{r['material']:11} {r['codec']:10} {r['ratio']:7.3f} "
            f"{1 - r['ratio']:6.1%} {r['enc_mbps']:7.2f}MB/s {r['dec_mbps']:7.2f}MB/s"
        )

    for f in failed:
        print("FAIL " + f)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
