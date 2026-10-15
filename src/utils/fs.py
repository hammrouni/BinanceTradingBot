"""fs.py - crash-safe file helpers."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path | str, text: str) -> None:
    """Write `text` to `path` via a temp file + os.replace so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path | str, data: Any, indent: int = 2) -> None:
    """Serialise first (so a bad payload never touches the target), then atomically replace."""
    atomic_write_text(path, json.dumps(data, indent=indent))
