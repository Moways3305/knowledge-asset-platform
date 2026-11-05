"""CONNECT-only gateway for disposable model tests; never log request data."""

import ipaddress
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import select
import socket
import sys
import time

WORKSPACE_ENV = "KAP_REHEARSAL_ALIYUN_WORKSPACE_ID"


def workspace_host(workspace_id):
    # This rehearsal supports the explicitly selected Beijing workspace only.
    # An ID is a single DNS label, never an arbitrary URL or wildcard domain.
    if not isinstance(workspace_id, str) or not re.fullmatch(r"ws-[a-z0-9]{1,60}", workspace_id):
        raise ValueError("invalid Beijing workspace ID")
    return workspace_id + ".cn-beijing.maas.aliyuncs.com"


def allowed_hosts(workspace_id=""):
    return {
        "api.deepseek.com",
        workspace_host(workspace_id) if workspace_id else "dashscope.aliyuncs.com",
    }


ALLOWED = allowed_hosts(os.environ.get(WORKSPACE_ENV, ""))


def target(authority):
    host, separator, port = authority.rpartition(":")
    if not separator or host not in ALLOWED or port != "443":
        raise ValueError("destination denied")
    return host


def public_address(value):
    address = ipaddress.ip_address(value)
    if "%" in value or not address.is_global or address.is_multicast or address.is_reserved:
        raise ValueError("nonpublic destination denied")
    return str(address)


def resolve_public(host):
    if host not in ALLOWED:
        raise ValueError("destination denied")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("model DNS answer empty")
    for row in addresses:
        public_address(row[4][0])
    return addresses


def validate_model_hosts(mapping, allowed=None):
    expected = ALLOWED if allowed is None else allowed
    if not isinstance(mapping, dict) or set(mapping) != expected:
        raise ValueError("model DNS hosts differ from allowlist")
    result = {}
    for host, addresses in mapping.items():
        if not isinstance(addresses, list) or not 1 <= len(addresses) <= 128:
            raise ValueError("model DNS answers invalid")
        result[host] = sorted({public_address(address) for address in addresses})
    return result


def resolve_model_hosts():
    return validate_model_hosts(
        {host: sorted({row[4][0] for row in resolve_public(host)}) for host in sorted(ALLOWED)}
    )


def connect_public(host):
    addresses = resolve_public(host)
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
    if sys.argv[1:] == ["--resolve-model-hosts"]:
        print(json.dumps(resolve_model_hosts()))
    elif not sys.argv[1:]:
        ThreadingHTTPServer(("0.0.0.0", 18080), Handler).serve_forever()
    else:
        raise SystemExit("unknown gateway command")
