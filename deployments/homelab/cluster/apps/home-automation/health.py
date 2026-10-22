#!/usr/bin/env python3
"""Export loopback-only MQTT and Matter health that no external probe can reach."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import socket
import sys
import urllib.request


def mqtt_auth():
    def string(value):
        value = value.encode()
        return len(value).to_bytes(2, 'big') + value
    password = Path('/credentials/monitoring-password').read_text().strip()
    body = string('MQTT') + bytes([4, 0xC2, 0, 15])
    body += string('infra-health') + string('monitoring') + string(password)
    length, remaining = bytearray(), len(body)
    while True:
        value, remaining = remaining % 128, remaining // 128
        length.append(value | (128 if remaining else 0))
        if not remaining:
            break
    with socket.create_connection(('127.0.0.1', 1883), timeout=3) as connection:
        connection.sendall(b'\x10' + length + body)
        response = b''
        while len(response) < 4:
            chunk = connection.recv(4 - len(response))
            if not chunk:
                break
            response += chunk
        connection.sendall(b'\xe0\x00')
        return response == b'\x20\x02\x00\x00'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthz':
            body = b'ok\n'
        elif self.path == '/metrics':
            try:
                mqtt = int(mqtt_auth())
            except (OSError, ValueError):
                mqtt = 0
            try:
                with urllib.request.urlopen('http://127.0.0.1:5580', timeout=3) as response:
                    matter = int(response.status == 200)
            except OSError:
                matter = 0
            body = (f'home_automation_mqtt_authenticated {mqtt}\n'
                    f'home_automation_matter_available {matter}\n').encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == '__main__':
    # Python as container PID 1 must handle SIGTERM itself.
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    ThreadingHTTPServer(('', 9000), Handler).serve_forever()
