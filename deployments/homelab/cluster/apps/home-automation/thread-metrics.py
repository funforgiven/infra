#!/usr/bin/env python3
"""Export whether OTBR is attached to the Thread mesh, without any secrets."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import signal
import sys
import urllib.request


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthz':
            body = b'ok\n'
        elif self.path == '/metrics':
            try:
                with urllib.request.urlopen('http://127.0.0.1:8081/node/state', timeout=3) as response:
                    attached = int(json.load(response) in ('leader', 'router', 'child'))
            except (OSError, ValueError):
                attached = 0
            body = f'home_automation_thread_attached {attached}\n'.encode()
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
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    ThreadingHTTPServer(('', 9000), Handler).serve_forever()
