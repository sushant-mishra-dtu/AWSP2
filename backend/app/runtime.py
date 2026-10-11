"""Builds the process-wide service objects for the API and the scheduled job."""

from __future__ import annotations

from dataclasses import dataclass

from .alerts import Alerts
from .auth import LocalTokens
from .campus import Campus
from .config import Settings, load_settings
from .evidence import LocalEvidence, S3Evidence
from .notify import LocalNotifier, SnsNotifier
from .replay import ReplayStore
from .reports import Reports
from .service import Service
from .store import DynamoTable, SqliteTable


@dataclass
class Runtime:
    settings: Settings
    service: Service
    table: object
    tokens: LocalTokens | None
    notifier: object
    evidence: object
    campus: Campus
    alerts: Alerts
    reports: Reports

    def describe(self) -> dict:
        s = self.settings
        local = s.store == "local"
        return {
            "data_mode": self.service.mode,
            "store": self.table.kind,
            "auth": "cognito" if s.auth_mode == "cognito" else "local-dev-signin",
            "notifier": self.notifier.kind,
            "evidence": self.evidence.kind,
            "bedrock": "configured" if s.bedrock_model_id else "not_configured",
            "ai_wording": {
                "primary": f"Amazon Bedrock ({s.bedrock_model_id})" if s.bedrock_model_id else None,
                "fallback": f"NVIDIA API ({s.nvidia_model})" if s.nvidia_api_key else None,
                "always": "deterministic bulletin (no AI)",
            },
            "cognito": {"region": s.cognito_region, "user_pool_id": s.cognito_user_pool_id, "client_id": s.cognito_client_id}
            if s.auth_mode == "cognito" else None,
            "local_mode_notice": (
                "LOCAL MODE: records are stored in a SQLite file on this machine, sign-in is a local development login "
                "(not Cognito), notifications are prepared but NOT sent (no SNS), and photos are stored in a local folder. "
                "None of this is AWS."
            ) if local else None,
        }


def build(settings: Settings | None = None, clock=None, table=None, notifier=None, evidence=None) -> Runtime:
    s = settings or load_settings()
    replay = ReplayStore.load(s.replay_file) if s.data_mode == "replay" else None
    if table is None:
        table = DynamoTable(s.table_name) if s.store == "dynamodb" else SqliteTable(s.data_dir / "airwindow.sqlite")
    service = Service(s, replay, table=table, **({"clock": clock} if clock else {}))
    tokens = LocalTokens.from_file(s.data_dir / "local_auth_secret", s.local_auth_secret) if s.auth_mode == "local" else None
    if notifier is None:
        notifier = SnsNotifier(s.topic_arn) if s.notifier == "sns" else LocalNotifier()
    if evidence is not None:
        pass
    elif s.evidence == "s3":
        evidence = S3Evidence(s.evidence_bucket)
    else:
        signer = tokens.sign if tokens else LocalTokens.from_file(s.data_dir / "local_auth_secret").sign
        evidence = LocalEvidence(s.data_dir / "evidence", signer)
    campus = Campus(table, service, demo_mode=replay is not None)
    alerts = Alerts(table, campus, notifier, service, s.app_url)
    reports = Reports(table, campus, evidence)
    return Runtime(s, service, table, tokens, notifier, evidence, campus, alerts, reports)
