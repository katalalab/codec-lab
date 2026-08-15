"""codec-lab: 実フォーマットで使われているアルゴリズムを層ごとに再現する。

層の対応(README のロードマップと同じ並び):
  予測   png_filter, lpc
  変換   dct, mdct, dwt, color
  量子化 quant
  辞書   lz77, lzw, deflate
  符号化 huffman, rice, arith, rans
  完全性 crc32, sha256
"""

import bz2
import lzma
import zlib

from . import arith, deflate, huffman, lz77, lzw, pipeline, rans

# bytes -> bytes の可逆コーデック。bench.py と test_codecs.py が共有する。
# 標準ライブラリの 3 つは「越えるべき基準線」として並べてある。
LOSSLESS = {
    "huffman": (huffman.encode, huffman.decode),
    "arith": (arith.encode, arith.decode),
    "rans": (rans.encode, rans.decode),
    "lz77": (lz77.encode, lz77.decode),
    "lzw": (lzw.encode, lzw.decode),
    "deflate": (deflate.encode, deflate.decode),
    "zlib(ref)": (zlib.compress, zlib.decompress),
    "lzma(ref)": (lzma.compress, lzma.decompress),
    "bz2(ref)": (bz2.compress, bz2.decompress),
}

# 素材固有の合成コーデック(pipeline.py)。生バイト列だけでは形が分からないので、
# 呼ぶ側が素材の形(画像なら width, height, bpp)を渡して bytes -> bytes に束ねる。
BY_MATERIAL = {
    "image_raw": pipeline.image_codecs,
    "audio_le16": pipeline.audio_codecs,
}
