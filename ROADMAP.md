# ROADMAP

「今も現役で使われているアルゴリズム」の網羅表。
実装済み = `test_codecs.py` が通っているもの。

## 第 1 層 予測

| 手法 | 使われている場所 | 状態 |
| --- | --- | --- |
| PNG 5 フィルタ + 適応選択 | PNG | 実装済 `png_filter` |
| 固定予測器（0〜4 次差分） | FLAC / Shorten | 実装済 `lpc.FIXED` |
| LPC + Levinson-Durbin + 係数量子化 | FLAC / ALAC / WavPack | 実装済 `lpc` |
| MED / LOCO-I 予測 | JPEG-LS | 未 |
| イントラ予測 9 モード | H.264 | 未 |
| 動き補償 + サブピクセル補間 | H.264 / H.265 / VP9 / AV1 | 未 |
| CfL（輝度からの色差予測） | AV1 / JPEG XL | 未 |
| ステレオ相関除去（mid/side） | FLAC / MP3 / AAC | 未 |
| 長期予測 LTP | AAC / Opus | 未 |

## 第 2 層 変換

| 手法 | 使われている場所 | 状態 |
| --- | --- | --- |
| DCT-II / III 8x8 | JPEG / MPEG-2 | 実装済 `dct` |
| MDCT + サイン窓（TDAC） | MP3 / AAC / Vorbis / Opus | 実装済 `mdct` |
| Haar | 学習用 / 一部 | 実装済 `dwt.haar` |
| CDF 5/3 整数リフティング | JPEG2000 可逆 | 実装済 `dwt.cdf53` |
| RGB↔YCbCr (BT.601) | JPEG / MPEG | 実装済 `color` |
| YCoCg-R（可逆色変換） | H.264 可逆 / JPEG XL | 実装済 `color.ycocg_r` |
| 4:2:0 サブサンプリング | JPEG / H.26x | 実装済 `color.subsample_420` |
| CDF 9/7（非可逆） | JPEG2000 | 未 |
| 整数 DCT 4x4 / 8x8 | H.264 / H.265 | 未 |
| アダマール変換（DC 係数の二次変換） | H.264 | 未 |
| KBD 窓 / ブロック切替 | AAC | 未 `mdct.kbd_placeholder` |
| ポリフェーズフィルタバンク 32 帯域 | MP3 | 未 |
| LSF / 帯域分割 | Opus (SILK/CELT) | 未 |

## 第 3 層 量子化（= 認知境界の設計場所）

| 手法 | 使われている場所 | 状態 |
| --- | --- | --- |
| Annex K 量子化テーブル + 品質スケール | JPEG | 実装済 `quant` |
| zigzag 走査 | JPEG / MPEG | 実装済 `quant.ZIGZAG` |
| デッドゾーン量子化 | H.264 / AV1 | 未 |
| トレリス量子化（RD 最適化） | x264 / mozjpeg | 未 |
| 心理音響モデル（同時マスキング・時間マスキング） | MP3 / AAC | 未 |
| バーク尺度・臨界帯域 | MP3 / AAC | 未 |
| CSF に基づく可変テーブル生成 | mozjpeg / Guetzli | 未 |
| XYB 色空間 + Butteraugli | JPEG XL | 未 |
| SSIM / VMAF による品質評価 | 評価側 | 未 |

## 第 4 層 辞書

| 手法 | 使われている場所 | 状態 |
| --- | --- | --- |
| LZ77 / LZSS + ハッシュチェーン | zip / gzip / png | 実装済 `lz77` |
| LZW 可変符号幅 | GIF / TIFF / PDF | 実装済 `lzw` |
| DEFLATE（LZ77 + 二重ハフマン + 長さ/距離符号） | zip / gzip / png | 実装済 `deflate` |
| 最適パース（lazy matching / optimal parse） | zopfli / zstd | 未 |
| LZMA（レンジ符号 + コンテキストモデル） | 7z / xz | 未 |
| BWT + MTF | bzip2 | 未 |
| 静的辞書 + コンテキストモデリング | Brotli | 未 |
| リピートオフセット | zstd / LZMA | 未 |

## 第 5 層 エントロピー符号化

| 手法 | 使われている場所 | 状態 |
| --- | --- | --- |
| 正準ハフマン | DEFLATE / JPEG | 実装済 `huffman` |
| Rice / Golomb | FLAC / JPEG-LS | 実装済 `rice` |
| 適応算術符号 | JBIG / 汎用 | 実装済 `arith` |
| 静的 rANS | JPEG XL / AV1 / Oodle | 実装済 `rans` |
| 長さ制限ハフマン（package-merge） | DEFLATE 15bit / JPEG 16bit | 未 |
| tANS / FSE | zstd | 未 |
| CABAC（コンテキスト適応二値算術符号） | H.264 / H.265 | 未 |
| CAVLC | H.264 baseline | 未 |
| MQ-coder | JPEG2000 | 未 |
| コンテキスト混合 | PAQ / cmix | 未 |

## 第 6 層 完全性

| 手法 | 使われている場所 | 状態 |
| --- | --- | --- |
| CRC-32 (IEEE) | zip / gzip / png | 実装済 `crc32` |
| SHA-256 | 一般 | 実装済 `sha256` |
| Adler-32 | zlib | 未 |
| CRC-32C (Castagnoli) | iSCSI / btrfs | 未 |
| xxHash / BLAKE3 | zstd / 高速検証 | 未 |

## コンテナ / フォーマット組み立て

層が揃った先の「実際に読み書きできるようにする」段。

| 対象 | 状態 |
| --- | --- |
| PNG 読み書き（IHDR/IDAT/IEND + CRC） | 未 |
| JPEG ベースライン エンコーダ / デコーダ | 未 |
| GIF | 未 |
| zip アーカイブ | 未 |
| FLAC ストリーム（STREAMINFO + フレーム） | 未 |
| WebP (VP8 intra) | 未 |
| ISO BMFF (mp4 / mov) のボックス解析 | 未 |
| QuickTime / ProRes のフレーム構造 | 未 |
| H.264 Annex B NAL 分解 | 未 |
| Matroska | 未 |

## 実験したい仮説（第 3 層）

1. JPEG の量子化テーブルを CSF から生成しなおして、同じファイルサイズで
   SSIM / Butteraugli が改善するか。
2. 4:2:0 の間引きを単純平均から、輝度エッジを保つ加重平均に変えると
   色にじみがどれだけ減るか。
3. FLAC の Rice パーティション分割を可変にしたときの利得の上限。
4. 可逆（YCoCg-R + PNG フィルタ + rANS）が PNG / WebP-lossless に対して
   どこまで詰められるか。
5. 時間マスキングを使って、プリエコーが出ない範囲で MDCT のブロック長を
   どこまで伸ばせるか。
