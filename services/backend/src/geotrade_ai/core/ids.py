import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 UUID v7: 48-bit unix ms timestamp, then random bits. Sorts by creation time."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= (rand >> 68) << 64  # 12 bits rand_a
    value |= 0b10 << 62  # variant
    value |= rand & ((1 << 62) - 1)  # 62 bits rand_b
    return uuid.UUID(int=value)
