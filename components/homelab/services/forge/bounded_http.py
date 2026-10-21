"""Fail-closed request helpers and a slot-bounded HTTP server for cache services."""
from http.server import ThreadingHTTPServer
import socket
import threading


class Refused(Exception):
    def __init__(self, status=403):
        self.status = status


def require(ok, status=403):
    if not ok:
        raise Refused(status)


class BoundedServer(ThreadingHTTPServer):
    """Refuse beyond a fixed number of workers and bound each connection's lifetime."""
    daemon_threads = True

    def __init__(self, address, handler, slots, socket_timeout, deadline):
        super().__init__(address, handler)
        self.slots = threading.BoundedSemaphore(slots)
        self.socket_timeout, self.deadline = socket_timeout, deadline

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        # Bound headers as well as bodies: a slow header sender must not occupy
        # a slot forever before the handler starts.
        request.settimeout(self.socket_timeout)
        def close_request():
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        deadline = threading.Timer(self.deadline, close_request)
        deadline.daemon = True
        deadline.start()
        try:
            super().process_request_thread(request, address)
        finally:
            deadline.cancel()
            self.slots.release()

    def handle_error(self, *_):
        pass  # Do not print request objects, capability URLs or credentials.
