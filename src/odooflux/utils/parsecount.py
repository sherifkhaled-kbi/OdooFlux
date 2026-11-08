"""Process-wide count of file parses (T010, REQ-PRF-002): parsers call ``bump()`` on a cache miss, so a test or the
benchmark can show that an incremental re-run parsed nothing."""

_COUNT = [0]


def bump() -> None:
    _COUNT[0] += 1


def snapshot() -> int:
    return _COUNT[0]
