"""AWS adapters exercised against moto, a LOCAL AWS API EMULATOR.

These tests prove our boto3 calls are well-formed and our logic around them
(conditional writes, GSIs, filter policies, presigned POST, object checks) is
correct. They are NOT evidence that anything works in a real AWS account.
Note: moto auto-confirms SNS email subscriptions; real SNS keeps them pending
until the recipient clicks the confirmation link (tested with a stub below).
"""

import asyncio
import json
import os

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.auth import cognito_user_from_event
from app.config import Settings
from app.evidence import EvidenceError, S3Evidence
from app.main import create_app
from app.notify import SnsNotifier
from app.runtime import build
from app.store import ConditionFailed, DynamoTable

from .conftest import FakeClock
from .test_campus import ORG, PE, aq_payload

REGION = "ap-south-1"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_SESSION_TOKEN": "testing",
                 "AWS_DEFAULT_REGION": REGION, "AWS_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        yield


def make_table(name="airwindow-test"):
    ddb = boto3.resource("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=name, BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[
            {"IndexName": "gsi1", "KeySchema": [{"AttributeName": "gsi1pk", "KeyType": "HASH"}, {"AttributeName": "gsi1sk", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "gsi2", "KeySchema": [{"AttributeName": "gsi2pk", "KeyType": "HASH"}, {"AttributeName": "gsi2sk", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
    )
    return DynamoTable(name, resource=ddb)


def test_dynamo_conditional_writes_and_indexes():
    t = make_table()
    t.put({"pk": "ORG#1", "sk": "META", "gsi1pk": "OWNER#u", "gsi1sk": "ORG#1", "gsi2pk": "ENTITY#ORG", "gsi2sk": "a#1",
           "version": 1, "lat": 28.6315, "nested": {"x": 1.5}})
    with pytest.raises(ConditionFailed):
        t.put({"pk": "ORG#1", "sk": "META", "version": 1}, if_not_exists=True)
    item = t.get("ORG#1", "META")
    assert item["lat"] == 28.6315 and item["nested"]["x"] == 1.5 and isinstance(item["version"], int)
    t.put({**item, "version": 2}, expect_version=1)
    with pytest.raises(ConditionFailed):
        t.put({**item, "version": 3}, expect_version=1)  # stale writer loses
    assert [i["pk"] for i in t.query("OWNER#u", "ORG#", index="gsi1")] == ["ORG#1"]
    assert len(t.query("ENTITY#ORG", "", index="gsi2")) == 1
    for i in range(3):
        t.put({"pk": "ORG#1", "sk": f"HIST#2026-10-11T0{i}"})
    assert [i["sk"] for i in t.query("ORG#1", "HIST#", reverse=True, limit=2)] == ["HIST#2026-10-11T02", "HIST#2026-10-11T01"]


def test_sns_subscribe_filter_and_publish():
    sns = boto3.client("sns", region_name=REGION)
    topic = sns.create_topic(Name="airwindow-alerts")["TopicArn"]
    n = SnsNotifier(topic, client=sns)
    r = n.subscribe("org-a", "coordinator@example.org")
    attrs = sns.get_subscription_attributes(SubscriptionArn=r["subscription_arn"])["Attributes"]
    assert json.loads(attrs["FilterPolicy"]) == {"org_id": ["org-a"]}
    assert r["status"] == "confirmed"  # moto auto-confirms; real SNS returns pending until the link is clicked
    mid = n.publish("org-a", "Subject", "Body", {"kind": "test"})
    assert mid


def test_sns_pending_subscription_is_reported_pending():
    class PendingSns:
        def subscribe(self, **kw):
            return {"SubscriptionArn": "arn:aws:sns:ap-south-1:1:t:abc"}

        def get_subscription_attributes(self, **kw):
            return {"Attributes": {"PendingConfirmation": "true"}}

    n = SnsNotifier("arn:aws:sns:ap-south-1:1:t", client=PendingSns())
    assert n.subscribe("org-a", "x@example.org")["status"] == "pending_confirmation"
    assert n.refresh("pending confirmation") == "pending_confirmation"


def test_s3_evidence_presigned_post_and_content_check():
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="evidence", CreateBucketConfiguration={"LocationConstraint": REGION})
    ev = S3Evidence("evidence", client=s3)
    with pytest.raises(EvidenceError):
        ev.upload_target("k.png", "image/svg+xml", 10)
    t = ev.upload_target("reports/o/r/a.png", "image/png", 20)
    assert t["method"] == "POST" and t["fields"]["Content-Type"] == "image/png" and "policy" in {k.lower() for k in t["fields"]}
    policy = json.loads(__import__("base64").b64decode(t["fields"]["policy"]))
    assert ["content-length-range", 1, 5 * 1024 * 1024] in policy["conditions"]
    s3.put_object(Bucket="evidence", Key="reports/o/r/a.png", Body=b"\x89PNG\r\n\x1a\n" + b"\x00" * 12, ContentType="image/png")
    assert ev.verify("reports/o/r/a.png", "image/png") == 20
    s3.put_object(Bucket="evidence", Key="reports/o/r/b.png", Body=b"<svg onload=alert(1)>", ContentType="image/png")
    with pytest.raises(EvidenceError):
        ev.verify("reports/o/r/b.png", "image/png")
    assert "Contents" not in s3.list_objects_v2(Bucket="evidence", Prefix="reports/o/r/b.png")  # deleted
    assert "X-Amz-Signature" in ev.view_url("reports/o/r/a.png")


def test_cognito_claims_parsing():
    ev = {"requestContext": {"authorizer": {"jwt": {"claims": {
        "sub": "abc", "email": "c@example.org", "token_use": "id", "cognito:groups": "[reviewers coordinators]"}}}}}
    u = cognito_user_from_event(ev)
    assert u.sub == "abc" and u.groups == ("reviewers", "coordinators") and u.method == "cognito"
    assert cognito_user_from_event({"requestContext": {}}) is None
    access = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "abc", "token_use": "access"}}}}}
    assert cognito_user_from_event(access) is None  # ID tokens only


def _apigw_event(path, method="GET", body=None, claims=None):
    path, _, query = path.partition("?")
    ev = {
        "version": "2.0", "routeKey": f"{method} {path}", "rawPath": path, "rawQueryString": query,
        "headers": {"host": "x.execute-api.ap-south-1.amazonaws.com", "content-type": "application/json"},
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.9",
                                    "userAgent": "t"}, "stage": "$default", "requestId": "r", "routeKey": "x",
                           "accountId": "1", "apiId": "x", "domainName": "x", "domainPrefix": "x", "time": "t", "timeEpoch": 0},
        "body": json.dumps(body) if body is not None else None, "isBase64Encoded": False,
    }
    if claims:
        ev["requestContext"]["authorizer"] = {"jwt": {"claims": claims, "scopes": None}}
    return ev


def test_full_workflow_on_emulated_aws_through_lambda_handler(tmp_path, monkeypatch, router):
    """DynamoDB + SNS (moto) + Cognito claims (as API Gateway would pass them) through Mangum."""
    from app.main import make_lambda_handler

    table = make_table()
    sns = boto3.client("sns", region_name=REGION)
    topic = sns.create_topic(Name="airwindow-alerts")["TopicArn"]
    settings = Settings(data_dir=tmp_path, store="dynamodb", table_name="airwindow-test", auth_mode="cognito",
                        notifier="sns", topic_arn=topic)
    rt = build(settings, clock=FakeClock(), table=table, notifier=SnsNotifier(topic, client=sns))
    handler = make_lambda_handler(create_app(rt))
    router.add("air-quality-api.open-meteo.com", httpx.Response(200, json=aq_payload()))
    a = {"sub": "user-a", "email": "a@example.org", "token_use": "id"}
    b = {"sub": "user-b", "email": "b@example.org", "token_use": "id"}

    def call(path, method="GET", body=None, claims=None):
        r = handler(_apigw_event(path, method, body, claims), type("C", (), {"aws_request_id": "r"})())
        return r["statusCode"], json.loads(r["body"]) if r.get("body") else None

    assert call("/api/orgs")[0] == 401  # no verified claims
    st, org = call("/api/orgs", "POST", ORG, a)
    assert st == 200, org
    oid = org["org_id"]
    assert call(f"/api/orgs/{oid}/activities", "POST", PE, a)[0] == 200
    assert call(f"/api/orgs/{oid}/cards", claims=b)[0] == 404  # ownership enforced
    st, sub = call(f"/api/orgs/{oid}/subscriptions", "POST", {"email": "a@example.org"}, a)
    assert st == 200 and sub["status"] == "confirmed"  # moto auto-confirm (see module docstring)
    st, s1 = call(f"/api/orgs/{oid}/assess", "POST", None, a)
    st, s2 = call(f"/api/orgs/{oid}/assess", "POST", None, a)
    assert s1["alerts_created"] >= 1 and s2["alerts_created"] == 0
    # Cooldown is per activity occurrence: each upcoming occurrence's first warning is published once.
    assert s1["notifications"].get("publish_accepted") == s1["alerts_created"]
    st, alerts = call(f"/api/orgs/{oid}/alerts", claims=a)
    statuses = sorted(x["notification"]["status"] for x in alerts["alerts"])
    assert "publish_accepted" in statuses
    accepted = next(x for x in alerts["alerts"] if x["notification"]["status"] == "publish_accepted")
    assert accepted["notification"]["message_id"] and accepted["acknowledged"] is None
    # Scheduled-job path on the same emulated table: still no duplicates.
    again = asyncio.run(rt.alerts.assess_all("schedule"))["results"][0]
    assert again["alerts_created"] == 0
    st, imp = call("/api/impact?scope=all")
    assert imp["counters"]["notifications"]["publish_accepted"] == s1["alerts_created"]
