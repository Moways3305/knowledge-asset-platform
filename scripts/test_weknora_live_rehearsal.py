import copy
import io
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import weknora_live_egress as egress
import weknora_live_probe as probe
import weknora_live_rehearsal as live


class LiveTests(unittest.TestCase):
    def test_gateway_requires_no_host_source_or_secret_mount(self):
        source = Path(egress.__file__).read_text()
        args = live.gateway_runtime_args("fixed-image", source)
        self.assertNotIn("--mount", args)
        self.assertNotIn("--user", args)
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("fixed-image") + 1 :], ["-u", "-c", source])
        compile(source, "gateway", "exec")

    def test_gateway_exit_fails_before_attempting_readiness(self):
        with (
            patch.object(live.pg, "inspect", return_value={"State": {"Running": False}}),
            patch.object(live.subprocess, "run") as execute,
        ):
            with self.assertRaisesRegex(RuntimeError, "gateway exited"):
                live.wait_gateway("synthetic-gateway")
            execute.assert_not_called()

    def test_gateway_unhealthy_is_bounded_and_never_accepted(self):
        with (
            patch.object(live.pg, "inspect", return_value={"State": {"Running": True}}),
            patch.object(
                live.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)
            ) as execute,
            patch.object(live.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness timeout"):
                live.wait_gateway("synthetic-gateway")
            self.assertEqual(execute.call_count, 20)

    def test_only_exact_approved_tls_targets(self):
        for host in egress.ALLOWED:
            self.assertEqual(egress.target(host + ":443"), host)
            self.assertTrue(probe.endpoint_allowed("https://" + host + "/v1"))
        for authority in (
            "api.deepseek.com:80",
            "api.deepseek.com.evil:443",
            "api.deepseek.com@127.0.0.1:443",
            "127.0.0.1:443",
            "[::1]:443",
            "api.deepseek.com.:443",
            "example.com:443",
        ):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                egress.target(authority)
        for url in (
            "http://api.deepseek.com",
            "https://secret@api.deepseek.com",
            "https://api.deepseek.com:8443",
            "https://example.com",
            "",
        ):
            self.assertFalse(probe.endpoint_allowed(url))

    def test_dns_private_and_mixed_answers_denied_before_connect(self):
        for ips in (
            ("127.0.0.1",),
            ("10.0.0.1",),
            ("169.254.169.254",),
            ("2606:4700::1111", "::1"),
            ("1.1.1.1", "192.168.0.1"),
        ):
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]
            with (
                patch.object(socket, "getaddrinfo", return_value=answers),
                patch.object(socket, "socket") as connect,
            ):
                with self.assertRaises(ValueError):
                    egress.connect_public("api.deepseek.com")
                connect.assert_not_called()

    def test_validated_ip_used_without_second_resolution(self):
        address = ("1.1.1.1", 443)
        with (
            patch.object(
                socket,
                "getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", address)],
            ) as resolve,
            patch.object(socket, "socket") as factory,
        ):
            egress.connect_public("api.deepseek.com")
            resolve.assert_called_once()
            factory.return_value.connect.assert_called_once_with(address)

    def test_connect_tunnel_and_denial_on_real_local_sockets(self):
        server = egress.ThreadingHTTPServer(("127.0.0.1", 0), egress.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        outbound, echo = socket.socketpair()
        try:
            readiness = subprocess.run(
                [sys.executable, "-c", live.GATEWAY_CHECK, *map(str, server.server_address)],
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(readiness.returncode, 0, readiness.stderr)
            with socket.create_connection(server.server_address, timeout=3) as client:
                client.sendall(
                    b"CONNECT forbidden.invalid:443 HTTP/1.1\r\nHost: forbidden.invalid\r\n\r\n"
                )
                self.assertIn(b"403", client.recv(1024))
            with patch.object(egress, "connect_public", return_value=outbound):
                with socket.create_connection(server.server_address, timeout=3) as client:
                    echo.settimeout(3)
                    client.sendall(
                        b"CONNECT api.deepseek.com:443 HTTP/1.1\r\nHost: api.deepseek.com\r\n\r\n"
                    )
                    headers = b""
                    while b"\r\n\r\n" not in headers:
                        headers += client.recv(1024)
                    self.assertIn(b"200", headers)
                    client.sendall(b"synthetic-input")
                    self.assertEqual(echo.recv(1024), b"synthetic-input")
                    echo.sendall(b"synthetic-reply")
                    self.assertEqual(client.recv(1024), b"synthetic-reply")
        finally:
            echo.close()
            outbound.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_network_guard_rejects_extra_network_ports_and_privilege(self):
        run = Path("/synthetic")
        item = {
            "Config": {"Labels": {live.pg.LABEL: str(run)}},
            "HostConfig": {"PortBindings": {}, "Privileged": False},
            "NetworkSettings": {"Networks": {"internal": {}}},
        }
        live.assert_network(item, ["internal"], run)
        for section, key, value in (
            ("NetworkSettings", "Networks", {"internal": {}, "bridge": {}}),
            ("HostConfig", "PortBindings", {"8080/tcp": [{}]}),
            ("HostConfig", "Privileged", True),
        ):
            modified = copy.deepcopy(item)
            modified[section][key] = value
            with self.assertRaises(RuntimeError):
                live.assert_network(modified, ["internal"], run)

    def test_docx_fixture_is_valid_package_with_synthetic_content(self):
        with zipfile.ZipFile(io.BytesIO(probe.docx_bytes())) as z:
            self.assertEqual(len(z.namelist()), 3)
            for name in z.namelist():
                ET.fromstring(z.read(name))
            self.assertIn(b"OFFICECHECK4826", z.read("word/document.xml"))


if __name__ == "__main__":
    unittest.main()
