from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPLAY = BACKEND_DIR / "fixtures" / "replay_delhi.json"


def _load_dotenv() -> None:
    """Minimal .env loader for local development (no extra dependency)."""
    for candidate in (BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break


@dataclass(frozen=True)
class Settings:
    data_mode: str = "live"  # live | replay
    openaq_api_key: str = ""
    replay_file: Path = DEFAULT_REPLAY
    cors_origins: list[str] = field(default_factory=list)
    static_dir: Path | None = None

    @property
    def openaq_configured(self) -> bool:
        return bool(self.openaq_api_key)


def load_settings() -> Settings:
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        _load_dotenv()
    mode = os.environ.get("DATA_MODE", "live").strip().lower()
    if mode not in ("live", "replay"):
        mode = "live"
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    static = os.environ.get("STATIC_DIR")
    return Settings(
        data_mode=mode,
        openaq_api_key=os.environ.get("OPENAQ_API_KEY", "").strip(),
        replay_file=Path(os.environ.get("REPLAY_FILE") or DEFAULT_REPLAY),
        cors_origins=origins,
        static_dir=Path(static) if static else None,
    )
