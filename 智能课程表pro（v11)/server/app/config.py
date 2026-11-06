"""Runtime configuration loaded from environment variables and a local .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class AIConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> AIConfig:
        try:
            timeout = float(os.environ.get("TIMETABLE_AI_TIMEOUT", "60"))
        except ValueError:
            timeout = 60.0
        return cls(
            api_key=os.environ.get("TIMETABLE_AI_API_KEY", "").strip(),
            base_url=os.environ.get("TIMETABLE_AI_BASE_URL", "https://api.openai.com/v1").rstrip(
                "/"
            ),
            model=os.environ.get("TIMETABLE_AI_MODEL", "gpt-4o-mini"),
            timeout=max(5.0, min(timeout, 120.0)),
        )
