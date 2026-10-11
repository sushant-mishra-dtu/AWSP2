from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPLAY = BACKEND_DIR / "fixtures" / "replay_delhi.json"
DEFAULT_DATA_DIR = BACKEND_DIR / ".data"


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


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    v = os.environ.get(name, default).strip().lower()
    return v if v in allowed else default


@dataclass(frozen=True)
class Settings:
    data_mode: str = "live"  # live | replay
    openaq_api_key: str = ""
    replay_file: Path = DEFAULT_REPLAY
    cors_origins: list[str] = field(default_factory=list)
    static_dir: Path | None = None
    # Campus workflow backends. Defaults are LOCAL and labelled as such.
    store: str = "local"  # local (SQLite file) | dynamodb
    table_name: str = ""
    auth_mode: str = "local"  # local (dev sign-in) | cognito
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    notifier: str = "local"  # local (outbox, never sends) | sns
    topic_arn: str = ""
    evidence: str = "local"  # local files | s3
    evidence_bucket: str = ""
    bedrock_model_id: str = ""
    nvidia_api_key: str = ""
    nvidia_model: str = "nvidia/nemotron-3-super-120b-a12b"
    app_url: str = ""
    data_dir: Path = DEFAULT_DATA_DIR
    local_auth_secret: str = ""

    @property
    def openaq_configured(self) -> bool:
        return bool(self.openaq_api_key)

    @property
    def on_aws(self) -> bool:
        return self.store == "dynamodb"


def load_settings() -> Settings:
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        _load_dotenv()
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    static = os.environ.get("STATIC_DIR")
    return Settings(
        data_mode=_choice("DATA_MODE", "live", ("live", "replay")),
        openaq_api_key=os.environ.get("OPENAQ_API_KEY", "").strip(),
        replay_file=Path(os.environ.get("REPLAY_FILE") or DEFAULT_REPLAY),
        cors_origins=origins,
        static_dir=Path(static) if static else None,
        store=_choice("STORE", "local", ("local", "dynamodb")),
        table_name=os.environ.get("TABLE_NAME", ""),
        auth_mode=_choice("AUTH_MODE", "local", ("local", "cognito")),
        cognito_region=os.environ.get("COGNITO_REGION", os.environ.get("AWS_REGION", "")),
        cognito_user_pool_id=os.environ.get("COGNITO_USER_POOL_ID", ""),
        cognito_client_id=os.environ.get("COGNITO_CLIENT_ID", ""),
        notifier=_choice("NOTIFIER", "local", ("local", "sns")),
        topic_arn=os.environ.get("TOPIC_ARN", ""),
        evidence=_choice("EVIDENCE", "local", ("local", "s3")),
        evidence_bucket=os.environ.get("EVIDENCE_BUCKET", ""),
        bedrock_model_id=os.environ.get("BEDROCK_MODEL_ID", "").strip(),
        nvidia_api_key=os.environ.get("NVIDIA_API_KEY", "").strip(),
        nvidia_model=os.environ.get("NVIDIA_MODEL", "").strip() or "nvidia/nemotron-3-super-120b-a12b",
        app_url=os.environ.get("APP_URL", ""),
        data_dir=Path(os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR),
        local_auth_secret=os.environ.get("LOCAL_AUTH_SECRET", ""),
    )
