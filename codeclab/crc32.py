"""CRC-32 (IEEE 802.3)。zip・gzip・png(各チャンク)・Ethernet。

多項式による剰余なので、ビット誤りの検出には強いが改竄検出には使えない
(狙って同じ CRC を作れる)。png が CRC、zip が CRC、
コンテンツ同一性判定に sha256 が要るのはこの差。
"""

POLY = 0xEDB88320  # 0x04C11DB7 のビット反転。LSB-first 実装用

TABLE = []
for _n in range(256):
    _c = _n
    for _ in range(8):
        _c = (_c >> 1) ^ (POLY if _c & 1 else 0)
    TABLE.append(_c)


def crc32(data, crc=0):
    crc ^= 0xFFFFFFFF
    for b in data:
        crc = TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF
