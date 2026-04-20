"""在应用启动时尽早将 .env 写入 os.environ（不覆盖已有环境变量）。"""
from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def _merge_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


def load_dotenv_files() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    backend_dir = Path(__file__).resolve().parent
    repo_root = backend_dir.parent
    for env_path in (repo_root / ".env", backend_dir / ".env"):
        _merge_file(env_path)
