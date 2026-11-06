"""Cross-platform local server entry point: ``python -m server``."""

from __future__ import annotations

import os

import uvicorn


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    host = os.environ.get("TIMETABLE_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("TIMETABLE_PORT", "8000"))
    except ValueError:
        port = 8000
    uvicorn.run(
        "server.app.main:app",
        host=host,
        port=port,
        reload=_env_flag("TIMETABLE_RELOAD"),
    )


if __name__ == "__main__":
    main()
