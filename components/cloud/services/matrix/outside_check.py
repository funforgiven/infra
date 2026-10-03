"""AWS Lambda check independent of the homelab and its identity service."""

import json
import hmac
import os
import urllib.request
import boto3


def handler(_event, _context):
    if "requestContext" in _event:
        method = _event.get("requestContext", {}).get("http", {}).get("method")
        if method != "POST" or _event.get("rawPath") != "/heartbeat":
            return {"statusCode": 404, "body": ""}
        expected = boto3.client("secretsmanager").get_secret_value(
            SecretId=os.environ["HEARTBEAT_SECRET_ARN"]
        )["SecretString"]
        supplied = _event.get("headers", {}).get("authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + expected):
            return {"statusCode": 401, "body": ""}
        boto3.client("cloudwatch").put_metric_data(
            Namespace="Fahrican/Matrix",
            MetricData=[
                {
                    "MetricName": "DeliveryHeartbeat",
                    "Value": 1,
                }
            ],
        )
        return {"statusCode": 202, "body": ""}
    healthy = 1
    checks = {
        "https://matrix.fahrican.com/_matrix/client/versions": "versions",
        "https://matrix-auth.fahrican.com/.well-known/openid-configuration": "issuer",
        "https://auth.cloud.fahrican.com/.well-known/openid-configuration": "issuer",
    }
    for url, expected in checks.items():
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
                if response.status != 200 or not payload.get(expected):
                    healthy = 0
        except Exception:
            healthy = 0
    boto3.client("cloudwatch").put_metric_data(
        Namespace="Fahrican/Matrix",
        MetricData=[
            {
                "MetricName": "PublicAvailability",
                "Value": healthy,
            }
        ],
    )
    return {"healthy": bool(healthy)}
