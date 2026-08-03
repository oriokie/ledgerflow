"""Time-ordered UUIDv7 primary keys.

Random UUIDv4 keys fragment B-tree indexes at high insert volume (page splits
on every insert). UUIDv7 embeds a millisecond timestamp in the high bits, so
inserts land at the right edge of the index like a sequential key, while the
random tail keeps them non-enumerable. We use v7 for every PK in the system.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit big-endian ms timestamp | version | random."""
    unix_ms = int(time.time() * 1000)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF  # 12 bits
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF  # 62 bits

    value = (unix_ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand_b
    return uuid.UUID(int=value)
