"""CONNECT-only gateway for disposable model tests; never log request data."""

import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import select
import socket
import time

ALLOWED = {"api.deepseek.com", "dashscope.aliyuncs.com"}


def target(authority):
    host, separator, port = authority.rpartition(":")
    if not separator or host not in ALLOWED or port != "443":
        raise ValueError("destination denied")
    return host


def connect_public(host):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("nonpublic destination denied")
    for family, kind, protocol, _, address in addresses:
        connection = socket.socket(family, kind, protocol)
        connection.settimeout(10)
        try:
            connection.connect(address)  # Connect this validated IP, never re-resolve.
            return connection
        except OSError:
            connection.close()
    raise OSError("model connection failed")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    rbufsize = 0

    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        self.close_connection = True
        try:
            host = target(self.path)
        except ValueError:
            self.send_error(403)
            return
        try:
            upstream = connect_public(host)
        except (OSError, ValueError):
            self.send_error(502)
            return
        with upstream:
            self.send_response(200, "Connection established")
            self.end_headers()
            peers = (self.connection, upstream)
            deadline = time.monotonic() + 180
            transferred = 0
            while time.monotonic() < deadline and transferred < 16 * 1024**2:
                ready, _, _ = select.select(peers, [], [], 10)
                for source in ready:
                    try:
                        block = source.recv(65536)
                        if not block:
                            return
                        transferred += len(block)
                        peers[1 if source is peers[0] else 0].sendall(block)
                    except OSError:
                        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 18080), Handler).serve_forever()
