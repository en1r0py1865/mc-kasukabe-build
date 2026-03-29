from __future__ import annotations

import os
from pathlib import Path


def load_local_env(start: Path | None = None) -> None:
    """Load a local .env file into process env without overriding existing vars."""
    start = start or Path.cwd()

    candidates = [start]
    candidates.extend(start.parents)

    # Fallback: search from package directory upward (handles CWD outside project tree)
    pkg_root = Path(__file__).resolve().parent.parent
    if pkg_root not in candidates:
        candidates.append(pkg_root)
        candidates.extend(p for p in pkg_root.parents if p not in candidates)

    env_path = next((base / ".env" for base in candidates if (base / ".env").exists()), None)
    if env_path is None:
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
