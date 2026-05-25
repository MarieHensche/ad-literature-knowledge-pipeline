from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(env_path: Path = Path(".env")) -> None:
    """Load key=value pairs from .env without overriding real environment vars."""
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
