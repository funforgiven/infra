#!/usr/bin/env python3
"""Submit a critical unit failure to Matrix, with independent SMTP fallback."""

import json
import os
import smtplib
import socket
import ssl
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path


def notify(config, unit):
    host = socket.gethostname()
    message = f"Critical unit failed on {host}: {unit}"
    invocation = os.environ.get(
        "MONITOR_INVOCATION_ID", os.environ.get("INVOCATION_ID", "")
    )
    event_id = host + ":" + unit + ":" + invocation
    request = urllib.request.Request(
        config["url"],
        method="POST",
        headers={
            "Authorization": "Bearer " + config["token"],
            "Content-Type": "application/json",
        },
        data=json.dumps(
            {
                "producer_id": config["producer_id"],
                "event_id": event_id,
                "host": host,
                "unit": unit,
                "severity": "critical",
                "message": message,
            }
        ).encode(),
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 202:
                raise ValueError("notification was not durably accepted")
        return
    except Exception:
        pass
    smtp = config["smtp"]
    email = EmailMessage()
    email["From"], email["To"], email["Subject"] = smtp["from"], smtp["to"], message
    email.set_content(message + "\nMatrix intake was unavailable.\n")
    with smtplib.SMTP_SSL(
        smtp["host"],
        smtp.get("port", 465),
        timeout=20,
        context=ssl.create_default_context(),
    ) as connection:
        connection.login(smtp["username"], smtp["password"])
        connection.send_message(email)


if __name__ == "__main__":
    try:
        notify(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2])
    except Exception:
        raise SystemExit(
            "Matrix and independent email notification failed; secret diagnostics suppressed."
        ) from None
