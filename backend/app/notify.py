"""Opt-in email notifications.

SnsNotifier: one SNS topic; each email subscription carries a filter policy
on the ``org_id`` message attribute, so a publish reaches only that
organisation's *confirmed* subscribers. SNS only delivers to an email address
after its owner clicks the confirmation link, so "pending" and "confirmed"
are shown separately and publishing is skipped when nobody has confirmed.

LocalNotifier: used in local mode. It never sends anything; notifications are
recorded as "not_sent_local_mode" so nothing is presented as delivered.

Statuses tracked by the app (alerts.py):
  prepared -> publish_accepted (SNS returned a MessageId) | failed |
  no_confirmed_subscribers | suppressed_cooldown | not_sent_local_mode
Recipient acknowledgement is separate and only recorded when a coordinator
acknowledges the warning in the app. A successful publish is not proof that
anyone read the email.
"""

from __future__ import annotations

import json
import re
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


class NotifyError(Exception):
    pass


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local[:2] + "•••@" + domain) if domain else "•••"


class LocalNotifier:
    kind = "local-outbox"
    can_send = False

    def subscribe(self, org_id: str, email: str) -> dict[str, Any]:
        return {"status": "unavailable_local_mode", "subscription_arn": None}

    def refresh(self, subscription_arn: str | None) -> str:
        return "unavailable_local_mode"

    def unsubscribe(self, subscription_arn: str | None) -> None:
        return None

    def publish(self, org_id: str, subject: str, message: str, attributes: dict[str, str] | None = None) -> str:
        raise NotifyError("local mode: SNS is not configured, nothing was sent")


class SnsNotifier:
    kind = "sns"
    can_send = True

    def __init__(self, topic_arn: str, client: Any | None = None):
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client("sns", config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=5, read_timeout=10))
        self.client = client
        self.topic_arn = topic_arn

    def subscribe(self, org_id: str, email: str) -> dict[str, Any]:
        r = self.client.subscribe(
            TopicArn=self.topic_arn,
            Protocol="email",
            Endpoint=email,
            Attributes={"FilterPolicy": json.dumps({"org_id": [org_id]}), "FilterPolicyScope": "MessageAttributes"},
            ReturnSubscriptionArn=True,
        )
        arn = r.get("SubscriptionArn")
        return {"status": self.refresh(arn), "subscription_arn": arn}

    def refresh(self, subscription_arn: str | None) -> str:
        if not subscription_arn or subscription_arn.lower().startswith("pending"):
            return "pending_confirmation"
        try:
            attrs = self.client.get_subscription_attributes(SubscriptionArn=subscription_arn)["Attributes"]
        except Exception as exc:  # noqa: BLE001 - NotFound after unsubscribe/expiry
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("NotFound", "NotFoundException", "InvalidParameter"):
                return "not_found"
            raise
        if attrs.get("PendingConfirmation") == "true":
            return "pending_confirmation"
        return "confirmed"

    def unsubscribe(self, subscription_arn: str | None) -> None:
        if subscription_arn and not subscription_arn.lower().startswith("pending"):
            self.client.unsubscribe(SubscriptionArn=subscription_arn)

    def publish(self, org_id: str, subject: str, message: str, attributes: dict[str, str] | None = None) -> str:
        attrs = {"org_id": {"DataType": "String", "StringValue": org_id}}
        for k, v in (attributes or {}).items():
            attrs[k] = {"DataType": "String", "StringValue": str(v)[:256]}
        try:
            r = self.client.publish(TopicArn=self.topic_arn, Subject=subject[:99], Message=message, MessageAttributes=attrs)
        except Exception as exc:  # noqa: BLE001 - surface any SDK/service error as a failed publish
            raise NotifyError(f"SNS publish failed: {exc.__class__.__name__}") from exc
        mid = r.get("MessageId")
        if not mid:
            raise NotifyError("SNS publish returned no MessageId")
        return mid
