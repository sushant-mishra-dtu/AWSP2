"""The Lambda entry point (Mangum) handles API Gateway HTTP API (payload v2) events."""

import json

import app.main as main


def _event(path: str, method: str = "GET", query: str = "", body: str | None = None) -> dict:
    return {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {"host": "example.execute-api.ap-south-1.amazonaws.com", "content-type": "application/json"},
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "example",
            "domainName": "example.execute-api.ap-south-1.amazonaws.com",
            "domainPrefix": "example",
            "http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.1", "userAgent": "test"},
            "requestId": "id",
            "routeKey": "ANY /api/{proxy+}",
            "stage": "$default",
            "time": "11/Oct/2026:10:00:00 +0000",
            "timeEpoch": 1791712800000,
        },
        "body": body,
        "isBase64Encoded": False,
    }


class Ctx:
    function_name = "airwindow-api"
    aws_request_id = "req"


def test_health_through_lambda_handler():
    resp = main.handler(_event("/api/health"), Ctx())
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert body["mode"] in ("live", "replay")
    assert resp["headers"]["cache-control"] == "no-store"


def test_validation_error_through_lambda_handler():
    resp = main.handler(_event("/api/point", query="lat=999&lon=0"), Ctx())
    assert resp["statusCode"] == 422
