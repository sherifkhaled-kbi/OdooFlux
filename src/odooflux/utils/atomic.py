"""Atomic replacement of customer files (FR-005, R-02)."""

import os
import shutil
import tempfile
from pathlib import Path


def atomic_write_bytes(path, data: bytes) -> None:
    """Temp file in the target directory, fsync, os.replace. Temp file removed on error;
    the mode of an existing target is kept."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            shutil.copymode(path, tmp_name)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))
